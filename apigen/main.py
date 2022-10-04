import textwrap
import typing as t
from contextlib import contextmanager

import typer
import yaml

import apigen.openapi as openapi

from importlib_resources import files
import apigen.templates
from jinja2 import Environment, FunctionLoader
from enum import Enum, auto

JinjaEnv = Environment(
    loader=FunctionLoader(
        lambda tempalte: files(apigen.templates).joinpath(tempalte).read_text()
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)


def to_camel_case(s: str) -> str:
    return "".join(word.capitalize() for word in s.replace(" ", "_").split("_"))


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
    except Exception as exc:
        if isinstance(exc, ErrorReport):
            exc.args = (f"{msg}\n\nCaused by:\n{exc}", *exc.args[1:])
            raise
        else:
            raise ErrorReport(
                f"{msg}\n\nCaused by:\n{exc.__class__.__name__}: {exc}"
            ) from exc


TYPE_MAPPING = {"integer": "i64", "string": "String", "number": "f64"}


def get_reference_name(reference: openapi.SchemaReference) -> str:
    return reference.ref.split("/")[-1]


def get_schema_prop(title: str, schema: openapi.SchemaOrReference):

    if isinstance(schema, openapi.SCALAR):
        return {
            "doc": schema.description,
            "title": title,
            "type": TYPE_MAPPING[schema.type],
        }

    if isinstance(schema, openapi.SchemaReference):
        return {"doc": None, "title": title, "type": get_reference_name(schema)}

    raise NotImplementedError(f"Cannot serialize struct property {schema}")


def serialzie_props(
    properties: t.Dict[str, openapi.SchemaOrReference]
) -> t.List[t.Dict[str, str]]:
    props = list()
    for prop_title, prop in properties.items():
        with error_context(f"Could not serialize property {prop_title}"):
            props.append(get_schema_prop(prop_title, prop))
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
    return ValueError(f"Could not render {schema} as inline type")


def serialize_struct_or_vec(title: str, schema: openapi.Schema):
    assert (
        schema.title is None or title == schema.title
    ), "Title must be equal to schema name"

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
                props = serialzie_props(schema.properties)

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

    raise NotImplementedError(f"Unsupported schema type: {schema.type}")


ERRORCODE_NAME_MAPPING = {
    "200": "SUCCESS",
    "404": "NOT_FOUND",
    "400": "BAD_REQUEST",
    "403": "FORBIDDEN",
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


def get_parameter_type(loc: ParameterLocation, schema: openapi.SchemaOrReference):

    if loc == ParameterLocation.QUERY and isinstance(schema, openapi.SchemaReference):
        return None

    if loc == ParameterLocation.PATH and isinstance(schema, openapi.SCALAR):
        return f"web::Path<{render_inline(schema)}>"

    raise NotImplementedError(f"{loc} {schema}")


def render_response_type(schema: openapi.SchemaOrReference):
    if isinstance(schema, openapi.SCALAR):
        return render_inline(schema)
    else:
        return f"web::Json<{render_inline(schema)}>"


def render_error_and_method(service: openapi.Service):

    success_response = service.responses["200"].content["application/json"].schema_

    response_inline = render_response_type(success_response)

    error_type, error = render_error(service)

    parameters = list()

    for parameter in service.parameters:
        parameter_type = get_parameter_type(
            get_parameter_location(parameter.in_), parameter.schema_
        )

        if parameter_type is None:
            parameters = [{"name": "request", "type": "HttpRequest"}]
            break

        parameters.append(
            {
                "name": parameter.name,
                "type": parameter_type,
            }
        )

    method = {
        "doc": service.summary,
        "operation_id": service.operation_id,
        "response_type": response_inline,
        "error_type": error_type,
        "method": service.method,
        "path": service.path,
        "parameters": parameters,
    }

    return error, method


def _main(spec_file: typer.FileText):
    spec_obj = yaml.safe_load(spec_file.read())

    with error_context(f"Could not extract schemas"):
        schemas = openapi.extract_schemas(spec_obj)

    with error_context(f"Could not extract services"):
        services = openapi.extract_services(spec_obj)

    models = list()
    for name, schema in schemas.schemas.items():
        with error_context(f"Error processing schema {name}"):
            models.append(serialize_struct_or_vec(name, schema))

    errors = list()
    methods = list()
    for error in services:
        error, method = render_error_and_method(error)
        if error is not None:
            errors.append(error)
        methods.append(method)

    print(render_template("api.rs", models=models, errors=errors, methods=methods))


def main():
    typer.run(_main)
