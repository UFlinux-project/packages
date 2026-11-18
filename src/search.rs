use std::collections::{BTreeMap, HashMap, HashSet};

use base64::{Engine as _, engine::general_purpose::STANDARD};
use flate2::read::GzDecoder;
use pagefind_web::{SearchIndex, init_pagefind, load_filter_chunk, load_index_chunk};
use serde::Deserialize;
use unicode_categories::UnicodeCategories;
use unicode_normalization::{UnicodeNormalization, char::is_combining_mark};

type LoadChunk = fn(*mut SearchIndex, &[u8]) -> *mut SearchIndex;

const INDEX: &[u8] = include_bytes!("../target/catalog-index.json.gz");

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Row {
    pub url: String,
    pub name: String,
    pub version: String,
    pub repository: String,
    pub branch: String,
    pub architecture: String,
    pub license: String,
    pub build_time: f64,
}

#[derive(Deserialize)]
struct Bundle {
    metadata: String,
    indexes: Vec<String>,
    filters: Vec<String>,
    rows: HashMap<String, Row>,
}

#[derive(Deserialize)]
struct Match {
    #[serde(rename = "p")]
    hash: String,
    #[serde(rename = "s")]
    score: f64,
}

#[derive(Deserialize)]
struct Response {
    results: Vec<Match>,
}

pub struct Search {
    index: *mut SearchIndex,
    rows: HashMap<String, Row>,
}

impl Search {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let bundle: Bundle = serde_json::from_reader(GzDecoder::new(INDEX))?;
        let mut search = Self {
            index: init_pagefind(&STANDARD.decode(bundle.metadata)?),
            rows: bundle.rows,
        };
        if search.index.is_null() {
            return Err("Invalid Pagefind metadata".into());
        }
        let chunks: [(Vec<String>, LoadChunk); 2] = [
            (bundle.indexes, load_index_chunk),
            (bundle.filters, load_filter_chunk),
        ];
        for (chunks, load) in chunks {
            for chunk in chunks {
                search.index = load(search.index, &STANDARD.decode(chunk)?);
                if search.index.is_null() {
                    return Err("Invalid Pagefind index chunk".into());
                }
            }
        }
        Ok(search)
    }

    pub fn find(
        &self,
        term: &str,
        filters: BTreeMap<&str, &str>,
    ) -> Result<Vec<&Row>, serde_json::Error> {
        let exact_phrase = term.starts_with('"') && term.ends_with('"') && term.len() > 2;
        let original = term
            .chars()
            .filter(|c| "-+._".contains(*c) || !c.is_punctuation())
            .flat_map(char::to_lowercase)
            .collect::<String>()
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        let normalized: String = original.nfd().filter(|c| !is_combining_mark(*c)).collect();
        if !term.is_empty() && normalized.is_empty() {
            return Ok(Vec::new());
        }
        let is_package_name = term.starts_with(|c: char| c.is_ascii_alphanumeric())
            && term
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "-+._~".contains(c));
        let mut matches = self.run(&normalized, &original, &filters, exact_phrase)?;
        if is_package_name {
            let name = term.to_ascii_lowercase();
            let named_filters = filters
                .into_iter()
                .chain([("packageName", name.as_str())])
                .collect();
            let mut named = self.run("", "", &named_filters, false)?;
            let exact: HashSet<_> = named.iter().map(|row| row.hash.as_str()).collect();
            matches.retain(|row| !exact.contains(row.hash.as_str()));
            named.extend(matches);
            matches = named;
        }
        Ok(matches
            .into_iter()
            .map(|row| &self.rows[&row.hash])
            .collect())
    }

    fn run(
        &self,
        query: &str,
        original: &str,
        filters: &BTreeMap<&str, &str>,
        exact: bool,
    ) -> Result<Vec<Match>, serde_json::Error> {
        let sort = if query.is_empty() { "browse:asc" } else { "" };
        let json = pagefind_web::search(
            self.index,
            query,
            original,
            &serde_json::to_string(filters)?,
            sort,
            exact,
            false,
        );
        let mut response: Response = serde_json::from_str(&json)?;
        response.results.sort_by(|a, b| b.score.total_cmp(&a.score));
        Ok(response.results)
    }
}

impl Drop for Search {
    fn drop(&mut self) {
        if !self.index.is_null() {
            // Pagefind transfers ownership of its boxed search index to the caller.
            unsafe { drop(Box::from_raw(self.index)) };
        }
    }
}
