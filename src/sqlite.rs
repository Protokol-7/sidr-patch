use itertools::Itertools;
use simple_error::SimpleError;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

use crate::report::*;
use crate::shared::*;
use crate::utils::*;

use ese_parser_lib::ese_parser::FromBytes;
use sqlite::State;
use std::io::Write;

macro_rules! map_err(($result:expr) => ($result.map_err(|e| SimpleError::new(format!("{}", e)))));

fn sqlite_get_hostname(c: &sqlite::Connection) -> Result<String, SimpleError> {
    // We take the System.ComputerName field from each record, filter out any records
    // where the System.ItemType field is equal to ".url", and save the first one as the computer
    // name for the entire report.
    let q = "select WorkId as wId, Value
             from SystemIndex_1_PropertyStore_Metadata
             join SystemIndex_1_PropertyStore
             on Id = ColumnId
             where Name == 'System.ComputerName'
             and (
                 select Value
                 from SystemIndex_1_PropertyStore_Metadata
                 join SystemIndex_1_PropertyStore
                 on Id = ColumnId
                 where WorkId == wId
                 and Name == 'System.ItemType'
                 ) <> '.url' limit 1;"
        .to_string();
    let mut s = map_err!(c.prepare(q))?;
    if let Ok(State::Row) = s.next() {
        let val = map_err!(s.read::<Vec<u8>, _>("Value"))?;
        return Ok(String::from_utf8_lossy(&val).into_owned());
    }
    Err(SimpleError::new(
        "Empty field System.ComputerName".to_string(),
    ))
}

fn populate_property_id_maps<'a>(
    c: &sqlite::Connection,
    idToProp: &'a mut HashMap<i64, (String, i64)>,
    NameToId: &'a mut HashMap<String, i64>,
) -> Result<(), SimpleError> {
    let q = "select Id, Name, StorageType from SystemIndex_1_PropertyStore_Metadata";
    let s = map_err!(c.prepare(q))?;

    for row in s.into_iter().map(|row| row.unwrap()) {
        let id = row.read::<i64, _>("Id");
        let name = row.read::<&str, _>("Name").to_string();
        let storageType = row.read::<i64, _>("StorageType");

        idToProp.insert(id, (name.clone(), storageType));
        NameToId.insert(name, id);
    }
    Ok(())
}

// Scans every (WorkId, ColumnId, Value) row in SystemIndex_1_PropertyStore, assembles
// them into per-WorkId records the same way the original streaming loop did, and calls
// on_record once per complete record. Used for both the field-collection pass and the
// write pass below, so the two can never see a different set of records.
fn scan_records<F: FnMut(u32, &HashMap<i64, Vec<u8>>)>(
    c: &sqlite::Connection,
    idToProp: &HashMap<i64, (String, i64)>,
    mut on_record: F,
) -> Result<(), SimpleError> {
    let query = "select * from SystemIndex_1_PropertyStore";
    let mut s = map_err!(c.prepare(query))?;

    let mut record = HashMap::new();
    let mut workId_current = 0u32;
    while let Ok(State::Row) = s.next() {
        let workId = map_err!(s.read::<i64, _>("WorkId"))? as u32;
        if workId_current != workId {
            if !record.is_empty() {
                on_record(workId_current, &record);
                record.clear();
            }
            workId_current = workId;
        }
        let columnId = map_err!(s.read::<i64, _>("ColumnId"))?;
        // Newer Windows 11 builds can store storage-type-12 (date/integer) values as
        // native SQLite integers. Reading those as a blob would yield their decimal
        // text, so convert them to the 8-byte little-endian form used elsewhere.
        let is_int12 = matches!(s.column_type("Value"), Ok(sqlite::Type::Integer))
            && idToProp.get(&columnId).map_or(false, |p| p.1 == 12);
        let value = if is_int12 {
            map_err!(s.read::<i64, _>("Value"))?.to_le_bytes().to_vec()
        } else {
            map_err!(s.read::<Vec<u8>, _>("Value"))?
        };
        record.insert(columnId, value);
    }
    // handle last element
    if !record.is_empty() {
        on_record(workId_current, &record);
    }
    Ok(())
}

// Adds every field this record would contribute to a report (same storage-type filter
// as write_record_to_report) into `fields`, keyed by ColumnId so the eventual column
// order is deterministic and follows property discovery order rather than hash order.
fn collect_record_fields(
    record: &HashMap<i64, Vec<u8>>,
    idToProp: &HashMap<i64, (String, i64)>,
    fields: &mut BTreeMap<i64, String>,
) {
    for col in record.keys() {
        if let Some((property_name, storage_type)) = idToProp.get(col) {
            if *storage_type == 11 || *storage_type == 12 {
                fields
                    .entry(*col)
                    .or_insert_with(|| property_name.replace(".", "_"));
            }
        }
    }
}

// This report will provide information about all the files that have been indexed by Windows search,
// including the file name, path, and creation/modification dates.
pub fn sqlite_generate_report(
    f: &Path,
    report_prod: &ReportProducer,
    status_logger: &mut Box<dyn Write>,
    history: bool,
) -> Result<(), SimpleError> {
    writeln!(
        status_logger,
        "Processing SQLite db: {}",
        &f.to_string_lossy()
    )
    .map_err(|e| SimpleError::new(format!("{e}")))?;

    let c = map_err!(sqlite::Connection::open_with_flags(
        f,
        sqlite::OpenFlags::new().with_read_only()
    ))?;
    wsa_lib::register_win_search_collations(&c);

    let recovered_hostname = match sqlite_get_hostname(&c) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("sqlite_get_hostname() failed: {e}. Will use 'Unknown' as a hostname.");
            "Unknown".to_string()
        }
    };

    let mut idToProp = HashMap::<i64, (String, i64)>::new();
    let mut propNameToId = HashMap::<String, i64>::new();
    if populate_property_id_maps(&c, &mut idToProp, &mut propNameToId).is_err() {
        panic!("Unable to read property IDs.")
    };

    // Pass 1: the CSV writer (see report.rs) fixes its header to whatever fields the
    // first row written has. A record further down that introduces a field the first
    // one didn't have would otherwise end up as an unlabelled, column-misaligned
    // trailing value instead of a named column. So scan every record once first to
    // collect the full set of fields each report will ever see.
    let mut file_fields = BTreeMap::<i64, String>::new();
    let mut ie_fields = BTreeMap::<i64, String>::new();
    let mut act_fields = BTreeMap::<i64, String>::new();
    scan_records(&c, &idToProp, |_workId, record| {
        if is_internet_record(record, &propNameToId).is_ok() {
            collect_record_fields(record, &idToProp, &mut ie_fields);
        } else if is_activity_history_record(record, &propNameToId).is_ok() {
            collect_record_fields(record, &idToProp, &mut act_fields);
        } else {
            collect_record_fields(record, &idToProp, &mut file_fields);
        }
    })?;

    let (mut file_rep, mut ie_rep, mut act_rep) =
        init_reports(f, report_prod, &recovered_hostname, status_logger, None)?;

    file_rep.set_field("WorkId");
    for name in file_fields.values() {
        file_rep.set_field(name);
    }
    ie_rep.set_field("WorkId");
    for name in ie_fields.values() {
        ie_rep.set_field(name);
    }
    act_rep.set_field("WorkId");
    for name in act_fields.values() {
        act_rep.set_field(name);
    }

    // Pass 2: write every record for real, now that every report's header covers
    // every field that will be written to it.
    scan_records(&c, &idToProp, |workId, record| {
        if is_internet_record(record, &propNameToId).is_ok() {
            write_record_to_report(record, workId, &idToProp, &mut *ie_rep);
        } else if is_activity_history_record(record, &propNameToId).is_ok() {
            write_record_to_report(record, workId, &idToProp, &mut *act_rep);
        } else {
            write_record_to_report(record, workId, &idToProp, &mut *file_rep);
        }
    })?;

    if history {
        if let Err(e) = crate::carve::write_history_report(
            f,
            &c,
            &idToProp,
            report_prod,
            &recovered_hostname,
            status_logger,
        ) {
            eprintln!("History recovery failed for {}: {e}", f.to_string_lossy());
        }
    }
    Ok(())
}

fn write_record_to_report(
    record: &HashMap<i64, Vec<u8>>,
    workId: u32,
    idToProp: &HashMap<i64, (String, i64)>,
    report: &mut dyn Report,
) {
    report.create_new_row();
    report.insert_int_val("WorkId", workId as u64);

    for (col, val) in record.iter().sorted() {
        let property_name = idToProp.get(col);
        if let Some((property_name, storage_type)) = property_name {
            let property_name = property_name.replace(".", "_");
            match storage_type {
                11 => {
                    // inferred to be string type
                    report.insert_str_val(&property_name, String::from_utf8_lossy(val).into_owned())
                }
                12 => {
                    // inferred to be date type when "Date" present in property name
                    let is_date = property_name.contains("Date") || property_name.contains("Time");
                    match le_bytes_to_u64(val) {
                        Some(n) if is_date && val.len() == 8 => report.insert_str_val(
                            &property_name,
                            format_date_time(get_date_time_from_filetime(n)),
                        ),
                        // otherwise inferred to be int type
                        Some(n) if !is_date => report.insert_int_val(&property_name, n),
                        // unexpected length: keep the raw bytes instead of panicking
                        _ => report.insert_str_val(&property_name, bytes_to_hex(val)),
                    }
                }
                _ => { /* Storage type not supported. */ }
            }
        }
    }
}

fn is_internet_record(
    record: &HashMap<i64 /*ColumnId*/, Vec<u8> /*Value*/>,
    propNameToId: &HashMap<String, i64>,
) -> Result<(), SimpleError> {
    let targetUriId = propNameToId
        .get("System.Link.TargetUrl")
        .ok_or_else(|| SimpleError::new("Could not find System.Link.TargetUrl ID in map."))?;
    let targetUriVal = record
        .get(targetUriId)
        .ok_or_else(|| SimpleError::new("Could not find System.Link.TargetUrl field in record."))?;
    let uriValStr = String::from_utf8_lossy(targetUriVal).into_owned();
    if !(uriValStr.starts_with("http")) {
        return Err(SimpleError::new(
            "System.Link.TargetUrl does not start with http.",
        ));
    }
    Ok(())
}

fn is_activity_history_record(
    record: &HashMap<i64 /*ColumnId*/, Vec<u8> /*Value*/>,
    propNameToId: &HashMap<String, i64>,
) -> Result<(), SimpleError> {
    let itemTypeId = propNameToId
        .get("System.ItemType")
        .ok_or_else(|| SimpleError::new("Could not find System.ItemType ID in map."))?;
    let itemTypeVal = record
        .get(itemTypeId)
        .ok_or_else(|| SimpleError::new("Could not find System.ItemType field in record."))?;
    let itemTypeStr = String::from_utf8_lossy(itemTypeVal).into_owned();
    if itemTypeStr != "ActivityHistoryItem" {
        return Err(SimpleError::new(
            "System.ItemType is not ActivityHistoryItem.",
        ));
    }
    Ok(())
}

#[test]
fn test_get_property_id_map() {
    let f = "tests/testdata/Windows.db";
    let c = map_err!(sqlite::Connection::open_with_flags(
        f,
        sqlite::OpenFlags::new().with_read_only()
    ))
    .unwrap();
    let mut idToProp = HashMap::<i64, (String, i64)>::new();
    let mut PropNameToId = HashMap::<String, i64>::new();
    populate_property_id_maps(&c, &mut idToProp, &mut PropNameToId).unwrap();
    assert!(idToProp.len() == 597);
    assert!(PropNameToId.len() == idToProp.len());
}

// Modified for sidr-patch (2026-10-26): Registers Windows Search collations; native-integer storage-type-12 values; non-panicking value decoding; --history hook.
// Modified for sidr-patch (2026-10-28): Two-pass report generation (scan_records, collect_record_fields) so every CSV report's header covers every field its rows can have, not just whatever the first processed record happened to have.
// See CHANGES-PATCH.md. Original: https://github.com/strozfriedberg/sidr v0.9.2
