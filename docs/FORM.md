# The application form

How a name and an email become a PandaDoc document with every field placed and
assigned. Nobody deploying this needs to read it; it matters when the form
changes or a upload comes back blank.

**It never sends.** `integrations/pandadoc.py` has no send code path, asserted
over the parsed AST by `tests/unit/test_pandadoc.py`. You open the link, check
it, and send it yourself.

It is not on the schedule, because the gate is whether a guest has paid and
wants to join — a judgement nobody has asked this service to make.

---

## The club's bank details are not in this repository

The IBAN, BIC, bank, account owner and the signature on the welcome letter
belong to named people, and this repository is public. So:

- The committed source form has that column **emptied** —
  `scripts/redact_source_form.py` removed the text-showing operators. Covering
  them with a white rectangle would not have worked: the glyphs stay in the
  content stream, which is the same fact that makes the white field tags
  extractable.
- `scripts/build_form_fields.py` draws the values back in, from `BANK_IBAN`,
  `BANK_BIC`, `BANK_NAME` and `BANK_OWNER`, defaulting to obvious placeholders.
- The Dockerfile's `form` stage runs that with the build arguments, and the
  service stage sets the same values (plus `SIGNATURE_NAME`) as environment
  defaults for the email template.

One build supplies both, so the letter and the form cannot disagree.

**A build with no arguments still succeeds** and produces a complete form and
letter reading `DE00 0000 0000 0000 0000 00`, signed "The VP Membership". That is
deliberate: wrong in a way a guest queries rather than acts on. The first run of
such an image logs a warning naming the missing variables.

The club's original PDF, with the real details printed on it, must be kept
outside this repository. To regenerate the committed form from it:

```bash
uv run python scripts/redact_source_form.py --source /path/to/the/original.pdf
uv run python scripts/build_form_fields.py
uv run python scripts/preview_form_fields.py   # then LOOK at the PNGs
```

## The annotated PDF is a build artefact

The source form in `src/clubops/assets/CBT_application_form_2026_fees_v2.pdf` is flat —
`get_fields()` returns `None`, and all three pages have zero annotations. That
is why placing a signature in PandaDoc was manual work every single time:
PandaDoc has **no coordinate-placement API**, so field positions can only come
from inside the file you upload.

```bash
uv run python scripts/build_form_fields.py     # writes the annotated PDF + manifest
uv run python scripts/preview_form_fields.py   # renders it to build/form-preview/*.png
```

Both outputs are checked in:

- `src/clubops/assets/cbt_application_form_fields.pdf` — 44 fields
- `src/clubops/domain/application_fields.py` — the field-name manifest the
  runtime imports, so nothing parses a PDF to serve a request

Change the geometry only in the spec table at the top of `build_form_fields.py`,
then re-run both commands and **look at the PNGs**. The preview fills every
field with a deliberately long value, so overflow shows up before an upload does.
`tests/unit/test_form_fields_pdf.py` then re-checks the artefact: field count,
minimum box size, the role convention, and that the manifest still matches.

Note this cannot be a PandaDoc *template*. PandaDoc's "create template from file
upload" endpoint states plainly that form fields are not supported, so a stored
template cannot carry the placement. The repo holds the template; PandaDoc does
not keep a copy.

## Roles are geometry

Field names are `{role}__{name}`, and the role comes from where the field sits:
on pages 1-2 the left column is the applicant's and the right column the club
officer's, which is how the form is laid out and labelled. Page 3 is entirely
the applicant's. The one override is the sponsor line, which spans the full
width but is marked "completed by a club officer".

So adding a field means adding one row to the spec table. Its role follows.

## Which API key

PandaDoc issues two, and you want both.

**Sandbox** for the calibration upload below: free, and none of its limits
affect what calibration checks — a developer prefix on the document name and a
watermark on the PDF do not move a field. **Production** for real guests, because
those same two limits are exactly what you would not want on an application form
sent to somebody joining the club.

Sandbox allows 10 requests a minute against production's 300. The poll loop in
`integrations/pandadoc.py` backs off to stay inside that budget, and
`tests/unit/test_pandadoc.py` pins it — if you widen `poll_attempts` or shorten
`poll_interval`, that test is what tells you the sandbox will start returning
429s. A 429 there looks like a broken upload and is not one.

Put the sandbox key in your local `.env` and the production key in Secret
Manager for the deployed service.

## Secret

```bash
gcloud secrets create cbt-pandadoc-api-key --replication-policy=automatic
# then, without leaving the value in shell history:
gcloud secrets versions add cbt-pandadoc-api-key --data-file=-
```

Grant the runtime service account `roles/secretmanager.secretAccessor` on it as
for the others, and add it to the deploy's `--set-secrets`:

```
PANDADOC_API_KEY=cbt-pandadoc-api-key:latest
```

`PANDADOC_OFFICER_EMAIL` needs no setup — it defaults to
`cb.toastmasters.d95@gmail.com`, the club address printed on the form. Set it
only if somebody else countersigns.

Leaving the key unset does **not** break the twice-weekly email job. It shares
`load_settings()`, so the key is deliberately optional there; only the document
job refuses, with a named error.

## Creating one

```bash
# Locally. Honours DRY_RUN, which validates and prints without uploading —
# worth doing first, because a created document is real and has to be deleted
# by hand.
uv run python scripts/create_application_doc.py \
    --name "Ada Lovelace" --email ada@example.com

# Deployed.
curl -X POST "$SERVICE_URL/jobs/application-document" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"name": "Ada Lovelace", "email": "ada@example.com"}'
```

Both return the document id and the link to review it.

## Field tags, and why not PDF form fields

The form carries **PandaDoc field tags** — literal text like
`{textfield:applicant:lastname____}` drawn into the PDF in white, which PandaDoc
finds and swaps for a field. The alternative, native AcroForm fields with
`parse_form_fields: true`, places fields correctly but silently discards two
things PandaDoc's own docs confirm: required-ness (*"auto-placed fields are 'not
required' by default"*) and date fields. The Update Document API cannot set them
afterwards either — it changes field *values*, not field properties.

The two mechanisms are mutually exclusive: `parse_form_fields` must be `false`
for tags, and a file containing both produces duplicate fields.

Six uploads went into establishing the following, none of which is obvious and
most of which PandaDoc does not report. Each is now a test:

| rule | what breaks otherwise |
|---|---|
| curly braces `{}`, not `[]` | zero fields, silently |
| `*` attached to the type, `{checkbox*:role:id}` | zero fields, silently |
| tags drawn in white, **not** text render mode 3 | zero fields, silently |
| every tag id declared in the request's `fields` object | that tag is dropped, silently |
| tag ids unique | one of the pair is dropped, silently |
| tags in the page's own content stream | zero fields, silently |

"Silently" is the theme: PandaDoc returns 201, the document reaches
`document.draft`, and the form is simply blank. `scripts/diagnose_pandadoc.py`
exists because of this — it asks the `/details` endpoint what was actually
placed, which is the only reliable answer.

## Size and position are the tag

**A field is exactly as wide as its tag, and its height follows its width.**
That single fact explains most of the layout work:

- Checkboxes are sized by making the tag exactly `CHECKBOX_BOX_WIDTH` wide —
  the font is *computed* per checkbox to achieve it, landing near 1pt. The ids
  are short (`mtn`, `gf`, `f1`) for the same reason: every character has to fit
  inside 11 points, or the box covers the label beside it.
- The two signatures share one 120pt slot at 9pt. Left unequal, the officer's
  box came out visibly larger than the applicant's purely because its tag was
  padded wider.
- Long ids on a narrow slot make a field that runs into its neighbour. The four
  sponsor fields once rendered as a single bar across the page.

The build guards all of this: it fails on duplicate ids, on tags that run off
the page, and on any two fields whose boxes would collide, and it warns about
tags wider than the field they mark.

## White paints

Tags are white so they cannot be seen, per PandaDoc's instruction to match the
tag colour to the background. White is not invisible, though — white glyphs
erase whatever is under them, and three tags once cut holes in the form,
including *"14.50 EUR per month..."* in the right-hand column.

So tags are lifted clear of the printed rules they sit near, and
`test_the_tags_erase_nothing_but_the_circles_they_replace` renders the artefact
against the source and fails on a single unexpected pixel. The one intentional
erasure is the printed `O` beside each checkbox, which would otherwise show its
right-hand arc next to the box that replaces it.

## What to check on an upload

- Fields exist at all — `scripts/diagnose_pandadoc.py` reports the count.
- Required is set on the applicant fields and all three signatures. **Not
  returned by the API**; check it in the PandaDoc UI.
- The two dates offer a date picker rather than a free text box.
- Two recipients, with the left/right split assigned as intended.
- No box covering a label, and no two boxes overlapping.
