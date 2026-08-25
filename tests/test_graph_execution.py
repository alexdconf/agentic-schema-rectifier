import unittest
import io
from unittest.mock import MagicMock, patch

from schema_rectifier.core import build_graph
from schema_rectifier.utils import Status


from langgraph.checkpoint.memory import MemorySaver

class TestGraphExecution(unittest.TestCase):
    def setUp(self):
        self.llm = MagicMock()
        self.mock_structured_output = self.llm.with_structured_output.return_value
        self.mock_invoke = self.mock_structured_output.invoke
        self.memory = MemorySaver()
        self.graph = build_graph(self.llm, memory=self.memory)

    @patch("schema_rectifier.nodes._get_llm_response")
    @patch("schema_rectifier.nodes._get_destination_columns")
    @patch("schema_rectifier.nodes._get_storage_client")
    @patch("schema_rectifier.nodes._load_data_dictionary")
    def test_end_to_end_pass(self, mock_load_data_dictionary, mock_get_storage, mock_dest, mock_llm_response):
        mock_load_data_dictionary.return_value = []
        # 1. Create in-memory mock streams
        in_stream = io.StringIO("col_c,col_a\n1,2\n3,4\n")
        out_stream = io.StringIO()
        out_stream.close = lambda: None
        mock_blob = MagicMock()
        # Route "r" to in_stream, "w" to out_stream
        mock_blob.open.side_effect = lambda mode, **kwargs: in_stream if "r" in mode else out_stream
        mock_blob.download_as_bytes.return_value = in_stream.getvalue().encode("utf-8")
        mock_client = MagicMock()
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_get_storage.return_value = mock_client
        mock_dest.return_value = ["col_a", "col_b"]
        mock_llm_response.return_value = '{"column_diff": [{"source_column": "col_c", "destination_column": "col_b"}]}'
        config = {"configurable": {"thread_id": "1"}}
        state = {
            "messages": [],
            "retry_count": 0,
            "input_gcs_uri": "gs://b/in.csv",
            "output_gcs_uri": "gs://b/out.csv"
        }
        # Run until breakpoint
        result = self.graph.invoke(state, config=config)
        self.assertEqual(result["status"], Status.VALID)
        # Resume with approval -> runs `load` node
        self.graph.update_state(config, {"human_approved": True})
        result = self.graph.invoke(None, config=config)
        self.assertEqual(result["status"], Status.VALID)
        
        # Verify written output header was rectified
        written_data = out_stream.getvalue()
        self.assertIn("col_b,col_a", written_data)
        self.assertIn("1,2", written_data)

    @patch("schema_rectifier.nodes._get_llm_response")
    @patch("schema_rectifier.nodes._get_destination_columns")
    @patch("schema_rectifier.nodes.pl.read_csv")
    @patch("schema_rectifier.nodes.pl.DataFrame.write_csv", create=True)
    def test_end_to_end_retry_loop(self, mock_write_csv, mock_read_csv, mock_dest, mock_llm_response):
        mock_df = type('MockDF', (), {'columns': ["col_a", "col_c"], 'rename': lambda self, x: self, 'write_csv': lambda self, x: None})()
        mock_read_csv.return_value = mock_df
        mock_dest.return_value = {"columns": ["col_a", "col_b"]}
        
        # LLM returns invalid mappings every time
        mock_llm_response.return_value = '{"column_diff": [{"source_column": "col_c", "destination_column": "invalid_col"}]}'

        config = {"configurable": {"thread_id": "2"}}
        state = {"messages": [], "retry_count": 0, "input_gcs_uri": "gs://b/f", "output_gcs_uri": "gs://b/out"}
        
        # Run until human_review breakpoint
        result = self.graph.invoke(state, config=config)
        
        # Resume graph with approval
        self.graph.update_state(config, {"human_approved": True})
        result = self.graph.invoke(None, config=config)

        self.assertEqual(result["status"], Status.VALID)
        self.assertGreater(result["retry_count"], 2)

    @patch("schema_rectifier.nodes._get_llm_response")
    @patch("schema_rectifier.nodes._get_destination_columns")
    @patch("schema_rectifier.nodes.pl.read_csv")
    @patch("schema_rectifier.nodes.pl.DataFrame.write_csv", create=True)
    def test_human_loop(self, mock_write_csv, mock_read_csv, mock_dest, mock_llm_response):
        mock_df = type('MockDF', (), {'columns': ["col_a", "col_c"], 'rename': lambda self, x: self, 'write_csv': lambda self, x: None})()
        mock_read_csv.return_value = mock_df
        mock_dest.return_value = {"columns": ["col_a", "col_b"]}
        
        # LLM initially returns a valid mapping
        mock_llm_response.return_value = '{"column_diff": [{"source_column": "col_c", "destination_column": "col_b"}]}'

        config = {"configurable": {"thread_id": "3"}}
        state = {"messages": [], "retry_count": 0, "input_gcs_uri": "gs://b/f", "output_gcs_uri": "gs://b/out"}
        
        # Run until human_review breakpoint
        result = self.graph.invoke(state, config=config)
        
        # Resume graph with rejection
        self.graph.update_state(config, {"human_approved": False})
        result = self.graph.invoke(None, config=config)
        
        # Should hit human_review breakpoint again
        
        # Resume graph with approval
        self.graph.update_state(config, {"human_approved": True})
        result = self.graph.invoke(None, config=config)

        self.assertEqual(result["status"], Status.VALID)
        self.assertEqual(result["column_diff"], [])

if __name__ == "__main__":
    unittest.main()
