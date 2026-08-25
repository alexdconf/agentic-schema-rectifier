import unittest
from unittest.mock import MagicMock, patch

from ollama import ResponseError
from pydantic import ValidationError

from schema_rectifier.nodes import single_column_name_mapping
from schema_rectifier.utils import State, Status


class TestMappingNode(unittest.TestCase):
    @patch("schema_rectifier.nodes._get_llm_response")
    def test_mapping_node_happy_path(self, mock_llm_response):
        mock_llm_response.return_value = '{"column_diff": [{"source_column": "col_c", "destination_column": "col_b"}]}'
        
        state: State = {"column_diff": ["col_c"], "messages": [], "retry_count": 0}
        result = single_column_name_mapping(state, "http://fake-llm")

        self.assertEqual(result["status"], Status.VALID)
        self.assertEqual(
            result["column_mappings"],
            [{"source_column": "col_c", "destination_column": "col_b"}]
        )

    @patch("schema_rectifier.nodes._get_llm_response")
    def test_mapping_node_failure_connection_error(self, mock_llm_response):
        mock_llm_response.side_effect = ConnectionError("Connection refused")

        state: State = {"column_diff": ["col_c"], "messages": [], "retry_count": 0}
        result = single_column_name_mapping(state, "http://fake-llm")

        self.assertEqual(result["status"], Status.INVALID)

    @patch("schema_rectifier.nodes._get_llm_response")
    def test_mapping_node_failure_response_error(self, mock_llm_response):
        mock_llm_response.side_effect = ResponseError("Ollama error")

        state: State = {"column_diff": ["col_c"], "messages": [], "retry_count": 0}
        result = single_column_name_mapping(state, "http://fake-llm")

        self.assertEqual(result["status"], Status.INVALID)

    @patch("schema_rectifier.nodes._get_llm_response")
    def test_mapping_node_failure_serialization_error(self, mock_llm_response):
        # We simulate a Pydantic validation error by passing invalid JSON structure
        mock_llm_response.return_value = '{"wrong_key": []}'

        state: State = {"column_diff": ["col_c"], "messages": [], "retry_count": 0}
        result = single_column_name_mapping(state, "http://fake-llm")

        self.assertEqual(result["status"], Status.INVALID)

    @patch("schema_rectifier.nodes._get_llm_response")
    def test_mapping_node_failure_empty_mapping(self, mock_llm_response):
        mock_llm_response.return_value = '{"column_diff": []}'

        state: State = {"column_diff": ["col_c"], "messages": [], "retry_count": 0}
        result = single_column_name_mapping(state, "http://fake-llm")

        self.assertEqual(result["status"], Status.INVALID)

    @patch("schema_rectifier.nodes._get_llm_response")
    def test_mapping_node_failure_max_retries(self, mock_llm_response):
        state: State = {"column_diff": ["col_c"], "messages": [], "retry_count": 3}
        result = single_column_name_mapping(state, "http://fake-llm")

        self.assertEqual(result["status"], Status.RETRY_OUT)
        # Should short-circuit and not call the LLM
        mock_llm_response.assert_not_called()

if __name__ == "__main__":
    unittest.main()
