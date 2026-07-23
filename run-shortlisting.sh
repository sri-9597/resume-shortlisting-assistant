 resume-shortlist run \
    --role qa-engineer \
    --csv candidates.csv \
    --resumes-dir resumes/ \
    --rubric examples/rubrics/qa-engineer.yaml \
    --jd examples/jd-qa-engineer.txt \
    --mode two-stage \
    --knockout-provider qwen \
    --provider claude-code --model claude-sonnet-5 \
    --top 50 --concurrency 4
