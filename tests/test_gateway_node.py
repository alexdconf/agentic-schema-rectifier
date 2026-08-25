import unittest
from unittest.mock import patch

from schema_rectifier.nodes import gateway_node
from schema_rectifier.utils import State


class TestGatewayNode(unittest.TestCase):
    @patch("schema_rectifier.nodes._get_destination_columns")
    @patch("schema_rectifier.nodes.pl.read_csv")
    def test_gateway_node_happy_path(self, mock_read_csv, mock_dest):
        mock_df = type('MockDF', (), {'columns': ["col_a", "col_b"]})()
        mock_read_csv.return_value = mock_df
        mock_dest.return_value = {"columns": ["col_a", "col_b"]}
        
        state: State = {"messages": [], "retry_count": 0, "input_gcs_uri": "gs://b/f"}
        result = gateway_node(state)
        
        self.assertEqual(result["column_diff"], [])
        self.assertIn("Columns are valid, nothing to do", result["messages"][0])

    @patch("schema_rectifier.nodes._get_destination_columns")
    @patch("schema_rectifier.nodes.pl.read_csv")
    def test_gateway_node_failure_mode_diff(self, mock_read_csv, mock_dest):
        mock_df = type('MockDF', (), {'columns': ["col_a", "col_b", "extra_col"]})()
        mock_read_csv.return_value = mock_df
        mock_dest.return_value = {"columns": ["col_a", "col_b"]}
        
        state: State = {"messages": [], "retry_count": 0, "input_gcs_uri": "gs://b/f"}
        result = gateway_node(state)
        
        self.assertEqual(result["column_diff"], ["extra_col"])
        self.assertIn("Columns are invalid, processing...", result["messages"][0])

if __name__ == "__main__":
    unittest.main()
