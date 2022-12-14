"""
Openapi Spec
"""

from __future__ import annotations

import typing as t

from pydantic import BaseModel, Field


class SchemaReference(BaseModel):
    ref: str = Field(alias="$ref")


class NumberSchema(BaseModel):
    type: t.Literal["number"] = "number"
    title: t.Optional[str]
    description: t.Optional[str]
    example: t.Optional[float]
    default: t.Optional[float]


class IntegerSchema(BaseModel):
    type: t.Literal["integer"] = "integer"
    title: t.Optional[str]
    description: t.Optional[str]
    example: t.Optional[int]
    default: t.Optional[int]


class StringSchema(BaseModel):
    type: t.Literal["string"] = "string"
    title: t.Optional[str]
    description: t.Optional[str]
    example: t.Optional[str]
    enum: t.Optional[t.List[str]]
    default: t.Optional[str]


class BooleanSchema(BaseModel):
    type: t.Literal["boolean"] = "boolean"
    title: t.Optional[str]
    description: t.Optional[str]
    example: t.Optional[bool]
    default: t.Optional[bool]


SCALAR = (NumberSchema, IntegerSchema, StringSchema, BooleanSchema)


class ObjectSchema(BaseModel):
    type: t.Literal["object"] = "object"
    required: t.List[str]
    title: t.Optional[str]
    description: t.Optional[str]
    properties: t.Optional[t.Dict[str, SchemaOrReference]]
    additionalProperties: t.Optional[SchemaOrReference]


class ArraySchema(BaseModel):
    type: t.Literal["array"] = "array"
    title: t.Optional[str]
    description: t.Optional[str]
    items: SchemaOrReference


Schema = t.Annotated[
    t.Union[
        BooleanSchema,
        NumberSchema,
        IntegerSchema,
        StringSchema,
        ObjectSchema,
        ArraySchema,
    ],
    Field(discriminator="type"),
]

SCHEMA = (
    BooleanSchema,
    NumberSchema,
    IntegerSchema,
    StringSchema,
    ObjectSchema,
    ArraySchema,
)

SchemaOrReference = t.Union[Schema, SchemaReference]

ObjectSchema.update_forward_refs()
ArraySchema.update_forward_refs()


class Components(BaseModel):
    schemas: t.Dict[str, Schema]


def extract_schemas(spec: t.Dict[t.Any, t.Any]):

    if "components" not in spec:
        return Components(schemas=dict())

    components = Components.parse_obj(spec["components"])

    return components


class ResponseContent(BaseModel):
    schema_: SchemaOrReference = Field(alias="schema")


class Response(BaseModel):
    description: str
    content: t.Dict[str, ResponseContent]


class Parameter(BaseModel):
    name: str
    required: bool
    description: str
    in_: str = Field(alias="in")
    schema_: SchemaOrReference = Field(alias="schema")


class Service(BaseModel):
    path: str
    method: str
    summary: str
    operation_id: str
    responses: t.Dict[str, Response]
    parameters: t.List[Parameter]


def _get_parameter_dict(spec: t.Dict[t.Any, t.Any]):

    if "components" not in spec:
        return dict()

    result = dict()
    for name, parameter in spec["components"]["parameters"].items():
        result[f"#/components/parameters/{name}"] = parameter
    return result


def _path_to_slug(path: str):
    return (
        path.strip("/")
        .replace("-", "_")
        .replace("/", "_")
        .replace("{", "")
        .replace("}", "")
        .lower()
        .replace("__", "_")
    )


def extract_services(spec: t.Dict[t.Any, t.Any]) -> t.List[Service]:
    parameters_dict = _get_parameter_dict(spec)

    services = list()
    for path, methods_and_service in spec["paths"].items():
        for method, service in methods_and_service.items():

            parameters = list()

            for parameter in service.get("parameters", list()):
                if isinstance(parameter, dict) and "$ref" in parameter:
                    parameter = parameters_dict[parameter["$ref"]]
                parameters.append(parameter)

            services.append(
                Service(
                    path=path,
                    method=method,
                    summary=service.get("summary", ""),
                    operation_id=service.get("operationId", _path_to_slug(path)),
                    responses={
                        k: Response.parse_obj(v)
                        for k, v in service["responses"].items()
                    },
                    parameters=parameters,
                )
            )
    return services
