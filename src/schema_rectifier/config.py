STANDARD_SCHEMA_LIST = [
    "state_code",
    "postal_code",
    "customer_id",
    "email",
    "transaction_amount",
    "transaction_timestamp",
]

CONFIG = {
    "incoming_columns": {"columns": ["st_cd", "txn_amt", "customer_id", "txx_ts"]},
    "standard_schema": {
        "label": "standard_schema",
        "version": "0.0.1",
        "columns": STANDARD_SCHEMA_LIST,
    },
}
