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
EXPOSE 8501

ENV DATABASE_URL="postgresql://postgres:postgres@db:5432/schema_staging"

# Run the application
CMD ["uv", "run", "streamlit", "run", "streamlit_ui/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
