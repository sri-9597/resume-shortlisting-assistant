# Examples

This directory holds sample data + rubrics for trying out the pipeline without
your own resumes.

## Contents

```
examples/
  rubrics/
    backend-engineer.yaml
    qa-engineer.yaml
    customer-support.yaml
  jd-backend-engineer.txt
  jd-qa-engineer.txt
  jd-customer-support.txt
  sample-candidates.csv     # 8 fake candidates, deterministic
  sample-resumes/           # drop your own PDFs here (one per candidate_id)
  make_samples.py           # regenerates sample-candidates.csv
```

## Trying the pipeline end-to-end

The CSV ships fully populated, but you need to supply your own resume PDFs.
Drop one `<candidate_id>.pdf` into `examples/sample-resumes/` for each row
you want to score. Missing PDFs are tolerated — those candidates will get
status `no_resume` and be skipped at the parse stage.

```bash
# Run the full pipeline against the backend-engineer rubric:
resume-shortlist run \
    --role demo-backend \
    --csv examples/sample-candidates.csv \
    --resumes-dir examples/sample-resumes \
    --rubric examples/rubrics/backend-engineer.yaml \
    --jd examples/jd-backend-engineer.txt \
    --provider claude --top 5
```

The output appears under `./demo-backend/`:

```
demo-backend/
  manifest.sqlite
  candidates.csv
  resumes/<id>.pdf  (and .txt after parse)
  scores/<id>.json
  ranked.csv
  ranked_full.csv
```

## Switching rubrics

Each rubric pairs with one JD. Try the same candidates against different
rubrics by changing both flags and using a different `--role` slug:

```bash
resume-shortlist run --role demo-qa \
    --csv examples/sample-candidates.csv \
    --resumes-dir examples/sample-resumes \
    --rubric examples/rubrics/qa-engineer.yaml \
    --jd examples/jd-qa-engineer.txt \
    --provider claude --top 5
```

## Regenerating sample-candidates.csv

```bash
python examples/make_samples.py
```

This is deterministic — useful if you've edited the file and want to revert,
or if you want to extend the sample set.
