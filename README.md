# Work Journal Mock

PC上の作業を一定間隔で記録し、振り返り用の詳細ログと共有向けの日報を分けて確認できるローカルWebアプリのモックです。監視目的ではなく、本人の振り返り支援と日報作成支援を意図しています。

## 特徴

- 既定では60秒ごとのスクリーンショット保存を行うローカル記録
- アクティブウィンドウタイトルとルールベース分類による簡易推定
- 低信頼時のみAI補完を挟める構造
- 自分用サマリーと公開用日報を別画面で確認
- JSONL保存で扱いやすく、後からOCRやAI連携を差し込みやすい構成

## ディレクトリ構成

```txt
work-journal/
  app.py
  recorder.py
  analyzer.py
  reporter.py
  storage.py
  sample_data.py
  ai_clients/
  prompts/
  templates/
  static/
  data/
  requirements.txt
  README.md
```

## セットアップ方法

`anaconda` の `py313` 環境を使う前提です。

```powershell
cd work-journal
conda activate py313
python -m pip install -r requirements.txt
```

OCRを使う場合は別途Tesseract本体のインストールが必要です。未導入でもアプリは動作し、OCRだけ無効になります。

## 起動方法

最も簡単な起動方法:

```powershell
cd work-journal
conda activate py313
python app.py
```

この環境では `conda run` が不安定だったため、必要なら同梱の起動スクリプトも使えます。

```powershell
cd work-journal
.\run_py313.ps1
```

`make` が使える環境であれば、以下でも起動できます。

```powershell
conda activate py313
make run
```

起動後は `http://127.0.0.1:8000` を開いてください。

## 記録開始方法

1. ダッシュボードを開く
2. 記録間隔やAI利用設定を必要に応じて調整する
3. `記録開始` を押す

停止するときは `停止` を押します。試しに1件だけ追加したい場合は `1回だけ記録` が使えます。

## 保存先

- スクリーンショット: `data/screenshots/YYYY-MM-DD/`
- ログ: `data/logs/activity_log.jsonl`
- サンプルログ: `data/logs/sample_activity_log.jsonl`

## サンプルデータ

初回起動時に最低限のサンプルデータを自動生成します。手動で作り直す場合:

```powershell
conda activate py313
python sample_data.py
```

## AI連携

外部AI連携は任意機能です。既定は `mock` で、`mistral` は画像付きの Chat Completions API を使う実装を入れています。`openai` はまだ雛形です。

### 利用できる provider 名

- `mock`
- `mistral` (実装済み)
- `openai` (雛形)

### 環境変数

```powershell
$env:AI_ENABLED="true"
$env:AI_PROVIDER="mistral"
$env:AI_CONFIDENCE_THRESHOLD="0.6"
$env:MISTRAL_API_KEY="..."
$env:MISTRAL_VISION_MODEL="mistral-small-latest"
```

`MISTRAL_VISION_MODEL` を変えれば、利用可能な他の vision 対応モデルにも差し替えできます。

`.env` を使う場合は `.env.example` をコピーして `.env` を作ってください。`run_py313.ps1` から起動した場合も `app.py` で読み込み、既存の同名環境変数より `.env` の値を優先します。

将来の実プロバイダ用:

```powershell
$env:OPENAI_API_KEY="..."
```

AI呼び出しは、ルールベース判定の信頼度が低い場合のみ行う想定です。APIキー未設定、タイムアウト、レート制限、画像送信失敗などが起きても、アプリ全体は落ちずルールベース推定へフォールバックします。

## 制限事項

- 現状はモックであり、推定精度は高くありません
- 生スクリーンショットの保存にはプライバシー上の注意が必要です
- 公開用日報は人が確認してから使う前提です
- 監視用途ではなく、本人の振り返り用途を想定しています
- OCRや外部AIは任意機能で、未設定時は簡易推定のみで動作します
- 画像を外部AIへ送る場合、個人情報や機密情報の送信リスクに注意が必要です
- Windows の Python / ネイティブ依存の組み合わせによっては OCR 側が不安定なことがあります。現状は OCR を子プロセス実行にしてあり、失敗時は OCR なしで継続します

## 今後の拡張候補

- OCR精度改善と日本語環境のセットアップ支援
- OpenAI / Mistral / Gemini / Claude / ローカルVLM の実接続
- マスキング処理の本実装
- 公開用レポートの秘匿ルール強化
- SQLite対応や検索機能追加
- AI呼び出し頻度制御、リトライ、キャッシュ

## 実装メモ

- `analyzer.py` に見やすいルールベース判定定義を配置
- `summarize_screenshot_with_ai(...)` を共通インターフェースとして定義
- `mask_sensitive_content(...)` を将来拡張ポイントとして追加
- スクリーンショット取得に失敗した場合でもダミー画像で継続し、落ちにくい実装にしてあります
