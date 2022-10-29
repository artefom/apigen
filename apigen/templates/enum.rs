// Custom error
#[derive(Debug, Serialize, Deserialize, Clone, PartialEq, Eq)]
pub enum {{ title }} {
    {% for variant in variants %}
    {{ variant | to_camel_case }},
    {% endfor %}
}
