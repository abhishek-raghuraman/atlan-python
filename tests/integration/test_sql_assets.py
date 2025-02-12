import logging
from typing import Callable, Optional, Type

import pytest

from pyatlan.cache.role_cache import RoleCache
from pyatlan.client.atlan import AtlanClient
from pyatlan.model.assets import (
    Asset,
    Column,
    Connection,
    Database,
    Readme,
    Schema,
    Table,
    View,
)
from pyatlan.model.enums import AtlanConnectorType
from pyatlan.model.response import A, AssetMutationResponse
from tests.integration.client import TestId

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def upsert(client: AtlanClient):
    guids: list[str] = []

    def _upsert(asset: Asset) -> AssetMutationResponse:
        _response = client.upsert(asset)
        if (
            _response
            and _response.mutated_entities
            and _response.mutated_entities.CREATE
        ):
            guids.append(_response.mutated_entities.CREATE[0].guid)
        return _response

    yield _upsert

    for guid in reversed(guids):
        response = client.purge_entity_by_guid(guid)
        if (
            not response
            or not response.mutated_entities
            or not response.mutated_entities.DELETE
        ):
            LOGGER.error(f"Failed to remove asset with GUID {guid}.")


def verify_asset_created(response, asset_type: Type[A]):
    assert response.mutated_entities


def verify_asset_updated(response, asset_type: Type[A]):
    assert response.mutated_entities
    assert response.mutated_entities.CREATE is None
    assert response.mutated_entities.UPDATE
    assert len(response.mutated_entities.UPDATE) == 1
    assets = response.assets_updated(asset_type=asset_type)
    assert len(assets) == 1


class TestConnection:
    connection: Optional[Connection] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        role = RoleCache.get_id_for_name("$admin")
        assert role
        connection_name = TestId.make_unique("INT")
        c = Connection.create(
            name=connection_name,
            connector_type=AtlanConnectorType.SNOWFLAKE,
            admin_roles=[role],
        )
        response = upsert(c)
        assert response.mutated_entities
        assert response.mutated_entities.CREATE
        assert len(response.mutated_entities.CREATE) == 1
        assert isinstance(response.mutated_entities.CREATE[0], Connection)
        assert response.guid_assignments
        c = response.mutated_entities.CREATE[0]
        c = client.get_asset_by_guid(c.guid, Connection)
        assert isinstance(c, Connection)
        TestConnection.connection = c

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestConnection.connection
        connection = TestConnection.connection
        description = f"{connection.description} more stuff"
        connection = Connection.create_for_modification(
            qualified_name=TestConnection.connection.qualified_name,
            name=TestConnection.connection.name,
        )
        connection.description = description
        response = upsert(connection)
        verify_asset_updated(response, Connection)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestConnection.connection
        connection = TestConnection.connection.trim_to_required()
        response = upsert(connection)
        assert response.mutated_entities is None


@pytest.mark.order(after="TestConnection")
class TestDatabase:
    database: Optional[Database] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        assert TestConnection.connection
        connection = TestConnection.connection
        database_name = TestId.make_unique("My_Db")
        database = Database.create(
            name=database_name,
            connection_qualified_name=connection.qualified_name,
        )
        response = upsert(database)
        assert response.mutated_entities
        assert response.mutated_entities.CREATE
        assert len(response.mutated_entities.CREATE) == 1
        assert isinstance(response.mutated_entities.CREATE[0], Database)
        assert response.guid_assignments
        database = response.mutated_entities.CREATE[0]
        client.get_asset_by_guid(database.guid, Database)
        TestDatabase.database = database

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestDatabase.database
        database = Database.create_for_modification(
            qualified_name=TestDatabase.database.qualified_name,
            name=TestDatabase.database.name,
        )
        description = f"{TestDatabase.database.description} more stuff"
        database.description = description
        response = upsert(database)
        verify_asset_updated(response, Database)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestDatabase.database
        database = TestDatabase.database.trim_to_required()
        response = upsert(database)
        assert response.mutated_entities is None


@pytest.mark.order(after="TestDatabase")
class TestSchema:
    schema: Optional[Schema] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        schema_name = TestId.make_unique("My_Schema")
        assert TestDatabase.database is not None
        schema = Schema.create(
            name=schema_name,
            database_qualified_name=TestDatabase.database.qualified_name,
        )
        response = upsert(schema)
        assert (schemas := response.assets_created(asset_type=Schema))
        assert len(schemas) == 1
        schema = client.get_asset_by_guid(schemas[0].guid, Schema)
        assert (databases := response.assets_updated(asset_type=Database))
        assert len(databases) == 1
        database = client.get_asset_by_guid(databases[0].guid, Database)
        assert database.attributes.schemas
        schemas = database.attributes.schemas
        assert len(schemas) == 1
        assert schemas[0].guid == schema.guid
        TestSchema.schema = schema

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestSchema.schema
        schema = TestSchema.schema
        description = f"{schema.description} more stuff"
        schema = Schema.create_for_modification(
            qualified_name=schema.qualified_name, name=schema.name
        )
        schema.description = description
        response = upsert(schema)
        verify_asset_updated(response, Schema)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestSchema.schema
        schema = TestSchema.schema.trim_to_required()
        response = upsert(schema)
        assert response.mutated_entities is None


@pytest.mark.order(after="TestSchema")
class TestTable:
    table: Optional[Table] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        table_name = TestId.make_unique("My_Table")
        assert TestSchema.schema is not None
        table = Table.create(
            name=table_name,
            schema_qualified_name=TestSchema.schema.qualified_name,
        )
        response = upsert(table)
        assert (tables := response.assets_created(asset_type=Table))
        assert len(tables) == 1
        table = client.get_asset_by_guid(guid=tables[0].guid, asset_type=Table)
        assert (schemas := response.assets_updated(asset_type=Schema))
        assert len(schemas) == 1
        schema = client.get_asset_by_guid(guid=schemas[0].guid, asset_type=Schema)
        assert schema.attributes.tables
        tables = schema.attributes.tables
        assert len(tables) == 1
        assert tables[0].guid == table.guid
        TestTable.table = table

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestTable.table
        table = TestTable.table
        description = f"{table.description} more stuff"
        table = Table.create_for_modification(
            qualified_name=table.qualified_name, name=table.name
        )
        table.description = description
        response = upsert(table)
        verify_asset_updated(response, Table)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestTable.table
        table = TestTable.table.trim_to_required()
        response = upsert(table)
        assert response.mutated_entities is None


@pytest.mark.order(after="TestTable")
class TestView:
    view: Optional[View] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        view_name = TestId.make_unique("My_View")
        assert TestSchema.schema is not None
        view = View.create(
            name=view_name,
            schema_qualified_name=TestSchema.schema.qualified_name,
        )
        response = upsert(view)
        assert response.mutated_entities
        assert response.mutated_entities.CREATE
        assert len(response.mutated_entities.CREATE) == 1
        assert isinstance(response.mutated_entities.CREATE[0], View)
        assert response.guid_assignments
        view = response.mutated_entities.CREATE[0]
        TestView.view = view

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestView.view
        view = TestView.view
        description = f"{view.description} more stuff"
        view = View.create_for_modification(
            qualified_name=view.qualified_name, name=view.name
        )
        view.description = description
        response = upsert(view)
        verify_asset_updated(response, View)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestView.view
        view = TestView.view.trim_to_required()
        response = upsert(view)
        assert response.mutated_entities is None


@pytest.mark.order(after="TestView")
class TestColumn:
    column: Optional[Column] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        column_name = TestId.make_unique("My_Column")
        assert TestTable.table is not None
        column = Column.create(
            name=column_name,
            parent_qualified_name=TestTable.table.qualified_name,
            parent_type=Table,
            order=1,
        )
        response = client.upsert(column)
        assert (columns := response.assets_created(asset_type=Column))
        assert len(columns) == 1
        column = client.get_asset_by_guid(asset_type=Column, guid=columns[0].guid)
        table = client.get_asset_by_guid(asset_type=Table, guid=TestTable.table.guid)
        assert table.attributes.columns
        columns = table.attributes.columns
        assert len(columns) == 1
        assert columns[0].guid == column.guid
        TestColumn.column = column

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestColumn.column
        column = TestColumn.column
        description = f"{column.description} more stuff"
        column = Column.create_for_modification(
            qualified_name=column.qualified_name, name=column.name
        )
        column.description = description
        response = upsert(column)
        verify_asset_updated(response, Column)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestColumn.column
        column = TestColumn.column.trim_to_required()
        response = upsert(column)
        assert response.mutated_entities is None


@pytest.mark.order(after="TestColumn")
class TestReadme:
    readme: Optional[Readme] = None

    def test_create(
        self,
        client: AtlanClient,
        upsert: Callable[[Asset], AssetMutationResponse],
    ):
        assert TestColumn.column
        readme = Readme.create(asset=TestColumn.column, content="<h1>Important</h1>")
        response = upsert(readme)
        assert (reaadmes := response.assets_created(asset_type=Readme))
        assert len(reaadmes) == 1
        assert (columns := response.assets_updated(asset_type=Column))
        assert len(columns) == 1
        readme = client.get_asset_by_guid(guid=reaadmes[0].guid, asset_type=Readme)
        TestReadme.readme = readme

    @pytest.mark.order(after="test_create")
    def test_create_for_modification(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestReadme.readme
        readme = TestReadme.readme
        description = f"{readme.description} more stuff"
        readme = Readme.create_for_modification(
            qualified_name=readme.qualified_name, name=readme.name
        )
        readme.description = description
        response = upsert(readme)
        verify_asset_updated(response, Readme)

    @pytest.mark.order(after="test_create")
    def test_trim_to_required(
        self, client: AtlanClient, upsert: Callable[[Asset], AssetMutationResponse]
    ):
        assert TestReadme.readme
        readme = TestReadme.readme
        readme = readme.trim_to_required()
        response = upsert(readme)
        assert response.mutated_entities is None
