FROM python:3.14-slim

# Install uv
RUN pip install uv

# Set the working directory
WORKDIR /app

# Copy the pyproject.toml and uv.lock first to leverage Docker cache
COPY pyproject.toml uv.lock ./

# Copy the rest of the application
COPY . .

# Install dependencies
RUN uv sync --frozen

# Expose the port the app runs on
EXPOSE 8080

# Run the cloud function
CMD ["uv", "run", "functions-framework", "--target", "process_gcs_file", "--source", "cloud_function/cloud_function.py", "--port", "8080", "--host", "0.0.0.0"]
