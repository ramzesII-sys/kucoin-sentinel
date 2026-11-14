name: sentinel
on:
  schedule:
    - cron: "17 * * * *"
  workflow_dispatch:
permissions:
  contents: write
concurrency:
  group: snapshot
  cancel-in-progress: false
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: snapshot
        run: python sentinel.py
      - name: commit
        run: |
          git config user.name sentinel-bot
          git config user.email sentinel@users.noreply.github.com
          git add snapshot.csv
          if git diff --cached --quiet; then
            echo "no changes"
            exit 0
          fi
          git commit -m "snapshot $(date -u +%FT%TZ)"
          for i in 1 2 3; do
            git pull --rebase -X theirs origin main && break || sleep 5
          done
          git push origin HEAD:main
      - name: telegram
        if: always()
        env:
          TGT: ${{ secrets.TG_TOKEN }}
          CHAT: ${{ secrets.TG_CHAT }}
        run: |
          if [ -s alert.txt ] && [ -n "$TGT" ]; then
            curl -s -m 15 "https://api.telegram.org/bot$TGT/sendMessage" \
              -d chat_id="$CHAT" --data-urlencode text@alert.txt || true
          fi
