{% if doc %}
{% for line in doc.splitlines() %}
/// {{line}}
{% endfor %}
{% endif %}
#[derive(Serialize, Deserialize, Clone, PartialEq)]
pub struct {{title}} {
  {% for prop in props %}
    {% if prop.doc %}
    {% for line in prop.doc.splitlines() %}
    /// {{line}}
    {% endfor %}
    {% endif %}
    {% if prop.title == "match" %}
    #[serde(rename = "match")]
    pub match_: {{ prop.type }},
    {% else %}
    pub {{ prop.title }}: {{ prop.type }},
    {% endif %}
  {% endfor %}
}
