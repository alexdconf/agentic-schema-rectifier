import unittest
from unittest.mock import patch

from schema_rectifier.nodes import single_column_name_mapping_validator
from schema_rectifier.utils import State, Status


class TestValidatorNode(unittest.TestCase):
    @patch("schema_rectifier.nodes._get_destination_columns")
    def test_validator_node_happy_path(self, mock_dest):
        mock_dest.return_value = {"columns": ["col_b", "col_d"]}
        
        state: State = {
            "column_mappings": [{"source_column": "col_c", "destination_column": "col_b"}],
            "messages": [], 
            "retry_count": 0
        }
        result = single_column_name_mapping_validator(state)
        
        self.assertEqual(result["status"], Status.VALID)
        self.assertEqual(result["invalid_mappings"], [])
        self.assertEqual(result["column_mappings"], [{"source_column": "col_c", "destination_column": "col_b"}])

    @patch("schema_rectifier.nodes._get_destination_columns")
    def test_validator_node_failure_invalid_mappings(self, mock_dest):
        mock_dest.return_value = {"columns": ["col_b"]}
        
        state: State = {
            "column_mappings": [
                {"source_column": "col_c", "destination_column": "col_b"},
                {"source_column": "col_e", "destination_column": "invalid_col"}
            ],
            "messages": [], 
            "retry_count": 0
        }
        result = single_column_name_mapping_validator(state)
        
        self.assertEqual(result["status"], Status.INVALID)
        self.assertEqual(result["invalid_mappings"], ["col_e"])
        self.assertEqual(result["column_mappings"], [{"source_column": "col_c", "destination_column": "col_b"}])

if __name__ == "__main__":
    unittest.main()
