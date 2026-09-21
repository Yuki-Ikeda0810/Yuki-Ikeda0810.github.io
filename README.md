# Yuki Ikeda Portfolio

日本語をルート `/`、英語を `/en/` にした静的サイト。

## Local preview

```bash
python -m http.server 8000
```

- 日本語: http://localhost:8000/
- English: http://localhost:8000/en/

`index.html` を直接開くことも可能。

## Structure

```text
/
├── index.html
├── en/
│   └── index.html
├── assets/
│   └── style.css
└── README.md
```

## researchmapとの同期

所属・経歴・論文・講演発表を公開APIから取得し、日本語・英語ページの専用領域だけを更新する。
プロジェクト紹介やAbout本文は変更しない。英語が未登録の項目は日本語を表示する。
論文と講演発表はAPIの応答に含まれる各カテゴリの新しい順で最大10件を表示し、全件はresearchmapへ誘導する。
現状、APIの初期応答はカテゴリごとに最大20件。経歴が応答件数を超えた場合は、不完全な経歴で上書きせず取得失敗として扱う。

### 手元で更新する

Python 3.10以降で、追加ライブラリは不要。

```bash
python scripts/sync_researchmap.py
```

保存済みデータだけで再生成する場合：

```bash
python scripts/sync_researchmap.py --offline
```

取得失敗時に前回のデータを使う場合は `--allow-stale` を指定する。
`data/researchmap.json` に取得日時と公開データを保存しています。ページにも最終取得日を表示する。
HTMLの `researchmap:...:start` と `researchmap:...:end` の間は自動生成されるため、直接編集すると次回更新で上書きされる。

### GitHub Pagesで自動更新する

1. このフォルダの内容（`.github/workflows/pages.yml`、`scripts`、`data`を含む）をGitHubの既定ブランチに反映する。
2. GitHubの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** に設定する。
3. **Actions → Sync researchmap and deploy Pages → Run workflow** で初回実行する。

以後は既定ブランチへの更新時と毎日08:10（日本時間）を目安に同期・公開します。GitHub側の混雑により遅延することがある。
公開APIの参照だけを使用するため、researchmapのAPIキーは不要。
ワークフローは取得成功時のデータをGitHub Actionsのキャッシュに保存し、取得失敗時はキャッシュを利用する。
キャッシュが利用できない場合はリポジトリ内の保存済みデータに戻ります。失敗はActionsの警告に表示され、取得日は更新されない。
生成結果は直接Pagesへ公開し、リポジトリのHTMLへ自動コミットはしない。

動作確認：

```bash
python -m unittest discover -s scripts -p "test_*.py"
```
