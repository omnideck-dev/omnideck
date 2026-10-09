from __future__ import annotations

from brokering.catalog import CatalogEntry
from integrations.catalog import IntegrationCatalogEntry
from brokering.drivers import BrokerDriver
from integrations.operations import OPERATIONS_BY_GROUP
from tests.integration.integrations.fixtures._host_paths import EMAIL_BROKER_HOST_PATHS
from tests.integration.integrations.fixtures.fake_email import FakeEmail


def make_fake_email_catalog(fake: FakeEmail) -> dict[str, CatalogEntry]:
    driver = BrokerDriver(
        id="test.email",
        command=("python", "-m", "brokering.brokers.email_broker"),
        env_injection={"email": "EMAIL_USER", "password": "EMAIL_PASS"},
        host_paths=EMAIL_BROKER_HOST_PATHS,
    )
    return {
        "icloud": IntegrationCatalogEntry(
            slug="icloud",
            title="Test iCloud",
            description="Test email and calendar",
            category="Test",
            driver=driver,
            operations=OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"],
            driver_config={
                "IMAP_HOST": fake.imap_host,
                "IMAP_PORT": str(fake.imap_port),
                "SMTP_HOST": fake.smtp_host,
                "SMTP_PORT": str(fake.smtp_port),
                "IMAP_TLS": "false",
                "SMTP_STARTTLS": "false",
            },
        ),
    }
