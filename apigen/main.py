import typing as t
from contextlib import contextmanager
from enum import Enum, auto

import typer
import yaml
from importlib_resources import files
from jinja2 import Environment, FunctionLoader

import apigen.openapi as openapi
import apigen.templates

JinjaEnv = Environment(
    loader=FunctionLoader(
        lambda tempalte: files(apigen.templates).joinpath(tempalte).read_text()
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)


def to_camel_case(some_string: str) -> str:
    return "".join(
        word.capitalize() for word in some_string.replace(" ", "_").split("_")
    )


JinjaEnv.filters["to_camel_case"] = to_camel_case


def render_template(src: str, **kwargs: t.Any):
    with error_context(f"Could not render {src}"):
        return JinjaEnv.get_template(src).render(**kwargs)


class ErrorReport(Exception):
    pass


@contextmanager
def error_context(
    msg: str,
) -> t.Generator[None, None, None]:
    try:
        yield
    except Exception as exc:  # pylint: disable=[W0703,]
        if isinstance(exc, ErrorReport):
            exc.args = (f"{msg}\n\nCaused by:\n{exc}", *exc.args[1:])
            raise
        raise ErrorReport(
            f"{msg}\n\nCaused by:\n{exc.__class__.__name__}: {exc}"
        ) from exc


TYPE_MAPPING = {
    "integer": "i64",
    "string": "String",
    "number": "f64",
    "boolean": "bool",
}


def get_reference_name(reference: openapi.SchemaReference) -> str:
    return reference.ref.split("/")[-1]


def _get_schema_prop(title: str, schema: openapi.SchemaOrReference):
    assert isinstance(title, str)
    if isinstance(schema, openapi.SCALAR):
        return {
            "doc": schema.description,
            "title": title,
            "type": TYPE_MAPPING[schema.type],
        }

    if isinstance(schema, openapi.SchemaReference):
        return {"doc": None, "title": title, "type": get_reference_name(schema)}

    if (
        isinstance(schema, openapi.ObjectSchema)
        and schema.additionalProperties is not None
    ):
        return {
            "doc": schema.description,
            "title": title,
            "type": f"HashMap<String,{render_inline(schema.additionalProperties)}>",
        }

    if isinstance(schema, openapi.ArraySchema):
        return {
            "doc": schema.description,
            "title": title,
            "type": f"Vec<{render_inline(schema.items)}>",
        }

    raise NotImplementedError(f"Cannot serialize struct property {schema}")


def get_schema_prop(title: str, schema: openapi.SchemaOrReference, prop_required: bool):
    rendered = _get_schema_prop(title, schema)
    if not prop_required:
        rendered["type"] = f"Option<{rendered['type']}>"
    return rendered


def serialzie_props(
    properties: t.Dict[str, openapi.SchemaOrReference], required: t.List[str]
) -> t.List[t.Dict[str, str]]:
    props = list()
    required_set = set(required)
    for prop_title, prop in properties.items():
        prop_required = prop_title in required_set
        with error_context(f"Could not serialize property {prop_title}"):
            props.append(get_schema_prop(prop_title, prop, prop_required))
    return props


def serialzie_additional_props(schema: openapi.ObjectSchema):
    assert schema.additionalProperties is not None


def get_array_schema_type(schema: openapi.ArraySchema):

    if isinstance(schema.items, openapi.SCALAR):
        with error_context(f"Unknown schema type {schema.items.type}"):
            return TYPE_MAPPING[schema.items.type]

    if isinstance(schema.items, openapi.SchemaReference):
        return get_reference_name(schema.items)

    raise NotImplementedError(
        f"Unsupported schema {schema.items}. Use reference instead"
    )


def render_inline(schema: openapi.SchemaOrReference):
    """
    Renders a type that can be imputed inline or raises an error
    """
    if isinstance(schema, openapi.SCALAR):
        return TYPE_MAPPING[schema.type]
    if isinstance(schema, openapi.SchemaReference):
        return get_reference_name(schema)
    if isinstance(schema, openapi.ArraySchema):
        return f"Vec<{render_inline(schema.items)}>"
    if isinstance(schema, openapi.ObjectSchema):
        if schema.additionalProperties is not None:
            return f"HashMap<String,{render_inline(schema.additionalProperties)}>"
    raise ValueError(f"Could not render {schema} as inline type")


def serialize_struct_or_vec(title: str, schema: openapi.Schema):
    assert (
        schema.title is None or title == schema.title
    ), "Title must be equal to schema name"
    assert isinstance(title, str)

    if isinstance(schema, openapi.ArraySchema):
        with error_context("Could not get vec type"):
            array_type = get_array_schema_type(schema)

        return render_template(
            "vec.rs",
            doc=schema.description,
            title=title,
            type=array_type,
        )

    if isinstance(schema, openapi.ObjectSchema):
        if schema.properties is not None:
            with error_context("Could not serialize properties"):
                props = serialzie_props(schema.properties, schema.required)

            return render_template(
                "struct.rs",
                doc=schema.description,
                title=title,
                props=props,
            )
        if schema.additionalProperties is not None:

            return render_template(
                "hashmap.rs",
                title=title,
                type=render_inline(schema.additionalProperties),
            )

    if isinstance(schema, openapi.StringSchema):
        if schema.enum:
            return render_template("enum.rs", title=title, variants=schema.enum)
        raise NotImplementedError("String schemas are not implemented")

    raise NotImplementedError(f"Unsupported schema type: {schema.type}")


ERRORCODE_NAME_MAPPING = {
    "100": "CONTINUE",
    "101": "SWITCHING_PROTOCOLS",
    "102": "PROCESSING",
    "200": "OK",
    "201": "CREATED",
    "202": "ACCEPTED",
    "203": "NON_AUTHORITATIVE_INFORMATION",
    "204": "NO_CONTENT",
    "205": "RESET_CONTENT",
    "206": "PARTIAL_CONTENT",
    "207": "MULTI_STATUS",
    "208": "ALREADY_REPORTED",
    "226": "IM_USED",
    "300": "MULTIPLE_CHOICES",
    "301": "MOVED_PERMANENTLY",
    "302": "FOUND",
    "303": "SEE_OTHER",
    "304": "NOT_MODIFIED",
    "305": "USE_PROXY",
    "307": "TEMPORARY_REDIRECT",
    "308": "PERMANENT_REDIRECT",
    "400": "BAD_REQUEST",
    "401": "UNAUTHORIZED",
    "402": "PAYMENT_REQUIRED",
    "403": "FORBIDDEN",
    "404": "NOT_FOUND",
    "405": "METHOD_NOT_ALLOWED",
    "406": "NOT_ACCEPTABLE",
    "407": "PROXY_AUTHENTICATION_REQUIRED",
    "408": "REQUEST_TIMEOUT",
    "409": "CONFLICT",
    "410": "GONE",
    "411": "LENGTH_REQUIRED",
    "412": "PRECONDITION_FAILED",
    "413": "PAYLOAD_TOO_LARGE",
    "414": "URI_TOO_LONG",
    "415": "UNSUPPORTED_MEDIA_TYPE",
    "416": "RANGE_NOT_SATISFIABLE",
    "417": "EXPECTATION_FAILED",
    "418": "IM_A_TEAPOT",
    "421": "MISDIRECTED_REQUEST",
    "422": "UNPROCESSABLE_ENTITY",
    "423": "LOCKED",
    "424": "FAILED_DEPENDENCY",
    "426": "UPGRADE_REQUIRED",
    "428": "PRECONDITION_REQUIRED",
    "429": "TOO_MANY_REQUESTS",
    "431": "REQUEST_HEADER_FIELDS_TOO_LARGE",
    "451": "UNAVAILABLE_FOR_LEGAL_REASONS",
    "500": "INTERNAL_SERVER_ERROR",
    "501": "NOT_IMPLEMENTED",
    "502": "BAD_GATEWAY",
    "503": "SERVICE_UNAVAILABLE",
    "504": "GATEWAY_TIMEOUT",
    "505": "HTTP_VERSION_NOT_SUPPORTED",
    "506": "VARIANT_ALSO_NEGOTIATES",
    "507": "INSUFFICIENT_STORAGE",
    "508": "LOOP_DETECTED",
    "510": "NOT_EXTENDED",
    "511": "NETWORK_AUTHENTICATION_REQUIRED",
}


def render_error(service: openapi.Service):
    error_variants = list()

    for code, response in service.responses.items():
        if code.startswith("2"):
            continue

        response_schema = response.content["application/json"].schema_
        if not isinstance(response_schema, openapi.StringSchema):
            raise NotImplementedError("Only strings in errors are allowed")
        if response_schema.enum is None:
            raise NotImplementedError("Must provide error variants")
        for variant in response_schema.enum:
            with error_context(f"Could not render error variant {code} {variant}"):
                error_variants.append(
                    {
                        "code": code,
                        "detail": variant,
                        "code_name": ERRORCODE_NAME_MAPPING[code],
                    }
                )

    if len(error_variants) == 0:
        return None, None

    error_type = to_camel_case(service.operation_id) + "Error"

    return error_type, render_template(
        "error.rs",
        error_type=error_type,
        operation_id=service.operation_id,
        variants=error_variants,
    )


class ParameterLocation(Enum):
    PATH = auto()
    QUERY = auto()


def get_parameter_location(in_str: str) -> ParameterLocation:
    with error_context(f"Could not understand parameter.in: {in_str}"):
        return {"path": ParameterLocation.PATH, "query": ParameterLocation.QUERY}[
            in_str
        ]


def get_parameter_type(
    loc: ParameterLocation,
    schema: openapi.SchemaOrReference,
    required: bool,
) -> t.Optional[str]:
    if loc == ParameterLocation.QUERY and isinstance(schema, openapi.SchemaReference):
        return None
    if isinstance(schema, openapi.SCALAR):
        rendered = render_inline(schema)
        if not required:
            rendered = f"Option<{rendered}>"
        return rendered
    raise NotImplementedError(f"{loc} {schema}")


def render_response_type(schema: openapi.SchemaOrReference):
    if isinstance(schema, openapi.SCALAR):
        return render_inline(schema)
    return f"web::Json<{render_inline(schema)}>"


def _sanitize_parameter_name(name: str) -> str:
    return name.lower().replace("-", "_")


def _get_new_provider_name(value: t.Any):
    if isinstance(value, bool):
        return "static_true" if value else "static_false"
    raise NotImplementedError(value)


def render_as_rust_value(val: t.Any):
    if isinstance(val, bool):
        return str(val).lower()
    return repr(val)


def get_provider_name(providers: t.Dict[str, t.Any], value: t.Any, value_type: str):
    if value in providers:
        return providers[value]["name"]

    name = _get_new_provider_name(value)

    providers[value] = {
        "name": name,
        "value": render_as_rust_value(value),
        "type": TYPE_MAPPING[value_type],
    }

    return name


def render_error_and_method(providers: t.Dict[str, t.Any], service: openapi.Service):

    success_response = service.responses["200"].content["application/json"].schema_

    response_inline = render_response_type(success_response)

    error_type, error = render_error(service)

    path_parameters = list()
    query_parameters = list()
    parameters = list()

    for parameter in service.parameters:

        location = get_parameter_location(parameter.in_)

        required = parameter.required
        default = None

        if isinstance(parameter.schema_, openapi.SCALAR):
            if parameter.schema_.default is not None:
                required = True
                default = get_provider_name(
                    providers, parameter.schema_.default, parameter.schema_.type
                )

        parameter_type = get_parameter_type(location, parameter.schema_, required)

        if parameter_type is None:
            parameters = [{"name": "request", "type": "HttpRequest"}]
            break

        sanitized = _sanitize_parameter_name(parameter.name)

        param = {
            "name": sanitized,
            "type": parameter_type,
            "rename": parameter.name if sanitized != parameter.name else None,
            "default": default,
        }

        if location == ParameterLocation.PATH:
            path_parameters.append(param)
        elif location == ParameterLocation.QUERY:
            query_parameters.append(param)
        else:
            raise NotImplementedError("Unknown path paramaeter location")

    method = {
        "doc": service.summary,
        "operation_id": service.operation_id,
        "response_type": response_inline,
        "error_type": error_type,
        "method": service.method,
        "path": service.path,
        "parameters": parameters,
        "query_parameters": query_parameters,
        "path_parameters": path_parameters,
    }

    return error, method


def _main(spec_file: typer.FileText):
    spec_obj = yaml.safe_load(spec_file.read())

    with error_context("Could not extract schemas"):
        schemas = openapi.extract_schemas(spec_obj)

    with error_context("Could not extract services"):
        services = openapi.extract_services(spec_obj)

    models = list()
    for name, schema in schemas.schemas.items():
        with error_context(f"Error reading /components/schemas/{name}"):
            models.append(serialize_struct_or_vec(name, schema))

    errors = list()
    methods = list()

    providers = dict()
    for error in services:
        error, method = render_error_and_method(providers, error)
        if error is not None:
            errors.append(error)
        methods.append(method)

    print(
        render_template(
            "api.rs",
            models=models,
            errors=errors,
            methods=methods,
            providers=list(providers.values()),
        )
    )


def main():
    typer.run(_main)
