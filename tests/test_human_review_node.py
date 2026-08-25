# import unittest
# from unittest.mock import patch

# from schema_rectifier.nodes import human_review
# from schema_rectifier.utils import State, Status


# class TestHumanReviewNode(unittest.TestCase):
#     def test_human_review_node_happy_path(self):
#         state: State = {
#             "column_mappings": [{"source_column": "col_c", "destination_column": "col_b"}],
#             "invalid_mappings": ["invalid_col"],
#             "messages": [], 
#             "retry_count": 0,
#             "human_approved": True,
#             "thread_id": "test_thread"
#         }
#         result = human_review(state, config={})
        
#         self.assertEqual(result["status"], Status.VALID)
#         self.assertEqual(result["invalid_mappings"], [])
#         self.assertEqual(result["column_diff"], [])
#         self.assertEqual(result["column_mappings"], [{"source_column": "col_c", "destination_column": "col_b"}])

#     def test_human_review_node_failure_rejection(self):
#         state: State = {
#             "column_mappings": [{"source_column": "col_c", "destination_column": "col_b"}],
#             "invalid_mappings": ["invalid_col"],
#             "messages": [], 
#             "retry_count": 0,
#             "human_approved": False,
#             "thread_id": "test_thread"
#         }
#         result = human_review(state, config={})
        
#         self.assertEqual(result["status"], Status.INVALID)
#         self.assertEqual(result["invalid_mappings"], [])
#         self.assertEqual(result["column_diff"], ["invalid_col"])
#         self.assertEqual(result["column_mappings"], [{"source_column": "col_c", "destination_column": "col_b"}])

# if __name__ == "__main__":
#     unittest.main()
