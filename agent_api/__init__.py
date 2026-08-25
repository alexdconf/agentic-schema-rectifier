from schema_rectifier.core import build_graph
from schema_rectifier.core import _initialize_model

llm_url = _initialize_model()
graph = build_graph(llm_url=llm_url)