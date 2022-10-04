// Custom error
#[derive(Debug, Serialize, Deserialize, Clone)]
pub enum {{ error_type }} {
    {% for variant in variants %}
    {{ variant.detail | to_camel_case }},
    {% endfor %}
}

impl Display for {{ error_type }} {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            {% for variant in variants %}
            {{error_type}}::{{variant.detail | to_camel_case}} => {
                write!(f, "{{variant.detail}}")
            },
            {% endfor %}
        }
    }
}

impl std::error::Error for {{error_type}} {}

impl ResponseError for {{error_type}} {
    fn status_code(&self) -> StatusCode {
        match self {
            {% for variant in variants %}
            {{error_type}}::{{variant.detail | to_camel_case}} => StatusCode::{{variant.code_name}},
            {% endfor %}
        }
    }
}
