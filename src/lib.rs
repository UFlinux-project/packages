mod search;

use std::{collections::BTreeMap, rc::Rc};

use js_sys::{Array, Date, Intl, Object};
use search::{Row, Search};
use wasm_bindgen::{JsCast, prelude::*};
use web_sys::{
    Document, Element, Event, EventTarget, FormData, HtmlElement, HtmlFormElement,
    HtmlInputElement, HtmlSelectElement, MouseEvent, UrlSearchParams, Window,
};

const FILTERS: [&str; 4] = ["repository", "branch", "architecture", "maintainer"];
const PAGE_SIZE: usize = 25;

type Result<T> = std::result::Result<T, JsValue>;

fn error(error: impl std::fmt::Display) -> JsValue {
    JsError::new(&error.to_string()).into()
}

#[derive(Default)]
struct State {
    term: String,
    filters: BTreeMap<&'static str, String>,
    older: bool,
    page: usize,
}

impl State {
    fn query(&self, page: usize) -> Result<String> {
        let query = UrlSearchParams::new()?;
        if !self.term.is_empty() {
            query.set("q", &self.term);
        }
        for name in FILTERS {
            if let Some(value) = self.filters.get(name) {
                query.set(name, value);
            }
        }
        if self.older {
            query.set("versions", "all");
        }
        if page > 1 {
            query.set("page", &page.to_string());
        }
        let query = String::from(query.to_string());
        Ok(if query.is_empty() {
            query
        } else {
            format!("?{query}")
        })
    }
}

struct App {
    window: Window,
    document: Document,
    search: Search,
    form: HtmlFormElement,
    czech: bool,
    numbers: Intl::NumberFormat,
}

impl App {
    fn element<T: JsCast>(&self, selector: &str) -> Result<T> {
        find(&self.document, selector)
    }

    fn text(&self, selector: &str, value: &str) -> Result<()> {
        self.element::<Element>(selector)?
            .set_text_content(Some(value));
        Ok(())
    }

    fn hide(&self, selector: &str, hidden: bool) -> Result<()> {
        self.element::<HtmlElement>(selector)?.set_hidden(hidden);
        Ok(())
    }

    fn term_input(&self) -> Result<HtmlInputElement> {
        self.element("[name=q]")
    }

    fn read(&self) -> Result<State> {
        let query = UrlSearchParams::new_with_str(&self.window.location().search()?)?;
        let term = query.get("q").unwrap_or_default();
        let term: String = term.trim().chars().take(200).collect();
        let older = query.get("versions").as_deref() == Some("all");
        let page = query
            .get("page")
            .and_then(|page| page.parse().ok())
            .unwrap_or(1)
            .max(1);
        let mut filters = BTreeMap::new();
        for name in FILTERS {
            let select = self.element::<HtmlSelectElement>(&format!("select[name={name}]"))?;
            select.set_value(&query.get(name).unwrap_or_default());
            let value = select.value();
            if value.is_empty() {
                select.set_value("");
            } else {
                filters.insert(name, value);
            }
        }
        self.term_input()?.set_value(&term);
        self.element::<HtmlInputElement>("[name=versions]")?
            .set_checked(older);
        Ok(State {
            term,
            filters,
            older,
            page,
        })
    }

    fn go(&self, state: State) -> Result<()> {
        let query = state.query(state.page)?;
        if self.window.location().search()? != query {
            self.window.history()?.push_state_with_url(
                &JsValue::NULL,
                "",
                Some(&(self.window.location().pathname()? + &query)),
            )?;
        }
        self.render()
    }

    fn submit(&self) -> Result<()> {
        let data = FormData::new_with_form(&self.form)?;
        let term = data
            .get("q")
            .as_string()
            .unwrap_or_default()
            .trim()
            .to_owned();
        let older = data.get("versions").as_string().as_deref() == Some("all");
        let filters = FILTERS
            .into_iter()
            .filter_map(|name| {
                let value = data.get(name).as_string()?;
                (!value.is_empty()).then_some((name, value))
            })
            .collect();
        self.go(State {
            term,
            filters,
            older,
            page: 1,
        })
    }

    fn number(&self, value: usize) -> String {
        self.numbers
            .format()
            .call1(&JsValue::UNDEFINED, &JsValue::from_f64(value as f64))
            .ok()
            .and_then(|formatted| formatted.as_string())
            .unwrap_or_else(|| value.to_string())
    }

    fn row(&self, data: &Row) -> Result<Element> {
        let row = self.document.create_element("tr")?;
        let heading = self.document.create_element("th")?;
        heading.set_attribute("scope", "row")?;
        let link = self.document.create_element("a")?;
        let prefix = if self.czech { "/cs" } else { "" };
        link.set_attribute("href", &format!("{prefix}{}", data.url))?;
        link.set_text_content(Some(&data.name));
        heading.append_child(&link)?;
        row.append_child(&heading)?;
        let built = if data.build_time > 0.0 {
            Date::new(&JsValue::from_f64(data.build_time * 1000.0))
                .to_iso_string()
                .as_string()
                .unwrap_or_default()
                .chars()
                .take(10)
                .collect()
        } else {
            String::new()
        };
        for value in [
            &data.version,
            &data.repository,
            &data.branch,
            &data.architecture,
            &data.license,
            &built,
        ] {
            let cell = self.document.create_element("td")?;
            cell.set_text_content(Some(if value.is_empty() { "—" } else { value }));
            row.append_child(&cell)?;
        }
        Ok(row)
    }

    fn render(&self) -> Result<()> {
        let mut state = self.read()?;
        let mut filters: BTreeMap<_, _> = state
            .filters
            .iter()
            .map(|(&key, value)| (key, value.as_str()))
            .collect();
        if !state.older {
            filters.insert("latest", "yes");
        }
        let results = self.search.find(&state.term, filters).map_err(error)?;
        let pages = results.len().div_ceil(PAGE_SIZE).max(1);
        state.page = state.page.min(pages);
        let query = state.query(state.page)?;
        let path = self.window.location().pathname()?;
        if self.window.location().search()? != query {
            self.window.history()?.replace_state_with_url(
                &JsValue::NULL,
                "",
                Some(&format!("{path}{query}")),
            )?;
        }
        let other = if self.czech { "/" } else { "/cs/" };
        self.element::<Element>("[data-alternate]")?
            .set_attribute("href", &format!("{other}{query}"))?;

        let offset = (state.page - 1) * PAGE_SIZE;
        let end = (offset + PAGE_SIZE).min(results.len());
        let rows = self.element::<Element>("#rows")?;
        rows.set_text_content(None);
        self.hide("#retry", true)?;
        self.hide("#table-wrap", results.is_empty())?;
        self.hide("#pagination", pages == 1)?;
        if results.is_empty() {
            return self.text(
                "#status",
                if self.czech {
                    "Žádné odpovídající balíčky."
                } else {
                    "No matching packages."
                },
            );
        }
        for item in &results[offset..end] {
            let row = self.row(item)?;
            rows.append_child(&row)?;
        }
        let (first, last, total) = (
            self.number(offset + 1),
            self.number(end),
            self.number(results.len()),
        );
        let status = if self.czech {
            format!("{first}–{last} z {total} výsledků")
        } else {
            format!("{first}–{last} of {total} results")
        };
        self.text("#status", &status)?;
        if pages > 1 {
            let page = state.page;
            let label = if self.czech {
                format!("Strana {page} z {pages}")
            } else {
                format!("Page {page} of {pages}")
            };
            self.text("#page-count", &label)?;
            for (selector, target, hidden) in [
                ("#previous", page - 1, page == 1),
                ("#next", page + 1, page == pages),
            ] {
                self.hide(selector, hidden)?;
                self.element::<Element>(selector)?
                    .set_attribute("href", &format!("{path}{}", state.query(target)?))?;
            }
        }
        Ok(())
    }

    fn show_error(&self) {
        let _ = self.hide("#retry", false);
        let _ = self.hide("#table-wrap", true);
        let _ = self.hide("#pagination", true);
        let _ = self.text(
            "#status",
            if self.czech {
                "Vyhledávání balíčků se nepodařilo načíst."
            } else {
                "Package search could not load."
            },
        );
    }

    fn listen(
        self: &Rc<Self>,
        target: &EventTarget,
        name: &str,
        action: impl Fn(&Self, Event) -> Result<()> + 'static,
    ) -> Result<()> {
        let app = Rc::clone(self);
        let handler = Closure::<dyn FnMut(Event)>::new(move |event| {
            if action(&app, event).is_err() {
                app.show_error();
            }
        });
        target.add_event_listener_with_callback(name, handler.as_ref().unchecked_ref())?;
        handler.forget();
        Ok(())
    }
}

fn find<T: JsCast>(document: &Document, selector: &str) -> Result<T> {
    document
        .query_selector(selector)?
        .and_then(|node| node.dyn_into().ok())
        .ok_or_else(|| error(format!("Missing element {selector}")))
}

#[wasm_bindgen(start)]
pub fn start() -> Result<()> {
    let window = web_sys::window().ok_or_else(|| error("Window unavailable"))?;
    let document = window
        .document()
        .ok_or_else(|| error("Document unavailable"))?;
    let czech = document
        .document_element()
        .and_then(|html| html.get_attribute("lang"))
        .as_deref()
        == Some("cs");
    let locale = Array::of1(&JsValue::from_str(if czech { "cs" } else { "en" }));
    let app = Rc::new(App {
        form: find(&document, "#filters")?,
        search: Search::new().map_err(error)?,
        numbers: Intl::NumberFormat::new(&locale, &Object::new()),
        czech,
        window,
        document,
    });
    app.listen(app.form.as_ref(), "submit", |app, event| {
        event.prevent_default();
        app.submit()
    })?;
    app.listen(app.form.as_ref(), "change", |app, event| {
        if event
            .target()
            .and_then(|target| target.dyn_into::<Element>().ok())
            .and_then(|element| element.get_attribute("name"))
            .as_deref()
            != Some("q")
        {
            app.submit()?;
        }
        Ok(())
    })?;
    app.listen(app.form.as_ref(), "reset", |app, event| {
        event.prevent_default();
        app.go(State {
            page: 1,
            ..State::default()
        })?;
        app.term_input()?.focus()
    })?;
    app.listen(app.window.as_ref(), "popstate", |app, _| app.render())?;
    for selector in ["#previous", "#next"] {
        let link = app.element::<Element>(selector)?;
        app.listen(link.as_ref(), "click", move |app, event| {
            let mouse: &MouseEvent = event.unchecked_ref();
            if mouse.button() != 0
                || mouse.meta_key()
                || mouse.ctrl_key()
                || mouse.shift_key()
                || mouse.alt_key()
            {
                return Ok(());
            }
            event.prevent_default();
            let link = app.element::<Element>(selector)?;
            app.window.history()?.push_state_with_url(
                &JsValue::NULL,
                "",
                link.get_attribute("href").as_deref(),
            )?;
            let status = app.element::<HtmlElement>("#status")?;
            status.set_tab_index(-1);
            status.focus()?;
            app.render()
        })?;
    }
    if !app.window.location().search()?.is_empty() {
        app.render()?;
    }
    app.form.remove_attribute("inert")?;
    app.element::<Element>("#pagination")?
        .remove_attribute("inert")?;
    Ok(())
}
