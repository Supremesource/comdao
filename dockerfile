FROM python:3.11

# Install Poetry
RUN pip install poetry

# Set the working directory
WORKDIR /app

# Copy the pyproject.toml and poetry.lock files
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Copy the source code
COPY ./src .
COPY env/* ./env/

# Expose the port on which the API will run
EXPOSE 8000

# Run the API
CMD ["poetry", "run", "uvicorn", "comdao.bot:app", "--host", "0.0.0.0", "--port", "8000"]
