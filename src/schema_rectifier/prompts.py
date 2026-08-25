SINGLE_COLUMN_NAME_MAPPING_PROMPT = """
            You are given a dataset with the following column name:
            {diff}

            You are also given a data dictionary with the following schema:
            {data_dictionary}

            Your job is to map the column {diff} to the correct standard name in the data dictionary.

            Return the mapping of the incoming column {diff} to the correct standard name.
            The mapping should be in the following format: {{ 'source_column': {diff}, 'destination_column': <destination_column_name> }}
        """
