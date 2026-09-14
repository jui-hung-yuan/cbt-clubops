# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# --- The application form -------------------------------------------------
# The club's IBAN, BIC, bank and account owner are a named person's, and this
# repository is public, so the committed form carries placeholders. This stage
# draws the real values in.
#
# A separate stage on purpose: it needs pypdf, which the service does not, and
# nothing but the finished PDF is copied forward.
#
# With no build args the form is still valid and still builds — it just says
# DE00 0000... That is the deliberate safe failure, and it is what
# `gcloud builds submit --tag` (which cannot pass build args) produces.
FROM python:3.12-slim AS form

RUN pip install --no-cache-dir uv==0.8.13
WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock* ./
# ./src carries both PDFs: the club's form with its bank column emptied, and the
# tagged artefact this stage overwrites.
COPY ./src ./src
COPY ./scripts/build_form_fields.py ./scripts/

ARG BANK_IBAN=""
ARG BANK_BIC=""
ARG BANK_NAME=""
ARG BANK_OWNER=""
ENV BANK_IBAN=$BANK_IBAN BANK_BIC=$BANK_BIC BANK_NAME=$BANK_NAME BANK_OWNER=$BANK_OWNER

# build() only, not main(): the field manifest in src/ is committed and must not
# be regenerated here, where nobody would see the diff.
RUN uv run --with pypdf python -c \
    "import sys; sys.path.insert(0, 'scripts'); import build_form_fields as b; b.build()"


# --- The service ----------------------------------------------------------
FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.8.13

WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock* ./

COPY ./src ./src

RUN uv sync --frozen

# The form with whatever details this build was given, replacing the
# placeholder copy that came in with ./src.
COPY --from=form /code/src/clubops/assets/cbt_application_form_fields.pdf \
    /code/src/clubops/assets/cbt_application_form_fields.pdf

# The same four values the form now shows, for the email template. One source,
# one build — so the letter and the form cannot disagree about where the money
# goes. SIGNATURE_NAME is email-only; it does not appear on the form.
ARG BANK_IBAN=""
ARG BANK_BIC=""
ARG BANK_NAME=""
ARG BANK_OWNER=""
ARG SIGNATURE_NAME=""
ENV BANK_IBAN=$BANK_IBAN \
    BANK_BIC=$BANK_BIC \
    BANK_NAME=$BANK_NAME \
    BANK_OWNER=$BANK_OWNER \
    SIGNATURE_NAME=$SIGNATURE_NAME

ARG AGENT_VERSION=0.0.0
ENV AGENT_VERSION=${AGENT_VERSION}

EXPOSE 8080

# One image, two services. The private service (clubops.web:app) holds the
# credentials and stays IAM-locked; the public Slack relay (clubops.slack_web:app)
# is deployed from the same image with APP_MODULE overridden, so the two can never
# drift apart at build time. Shell form so the variables expand.
ENV APP_MODULE=clubops.web:app

# The venv's uvicorn directly, not `uv run uvicorn`. `uv run` re-verifies the
# environment on every container start and rebuilds the local package — a second
# of cold start, every time, to redo what `uv sync --frozen` already did at build
# time. That second matters: Slack gives a slash command three seconds to
# answer, and a cold start that overruns it shows the board an "operation_timeout"
# for work that actually succeeded.
CMD /code/.venv/bin/uvicorn "$APP_MODULE" --host 0.0.0.0 --port "${PORT:-8080}"
