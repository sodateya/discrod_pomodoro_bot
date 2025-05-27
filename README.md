# Discord ポモドーロタイマーボット

Discord でポモドーロタイマーを管理できるボットです。音声通知付きで作業時間と休憩時間を管理できます。

## 機能

- 25 分の作業時間と 5 分の休憩時間を自動で繰り返し
- 作業開始・休憩開始時に音声通知
- スラッシュコマンド（`/pomodoro`）で簡単操作
- ボタンによる直感的な操作
- プライベートな通知（他のユーザーには見えない）

## セットアップ

### 必要なもの

- Python 3.8 以上
- FFmpeg
- Discord Bot Token

### インストール

1. リポジトリをクローン

```bash
git clone [リポジトリのURL]
cd discrod_pomodoro_bot
```

2. 仮想環境を作成して有効化

```bash
python3 -m venv venv
source venv/bin/activate
```

3. 必要なパッケージをインストール

```bash
pip install discord.py python-dotenv PyNaCl
```

4. FFmpeg のインストール（macOS）

```bash
brew install ffmpeg
```

5. 環境変数の設定
   `.env`ファイルを作成し、以下の内容を追加：

```
DISCORD_TOKEN=あなたのボットトークン
```

6. 音声ファイルの準備
   `sounds`ディレクトリを作成し、以下のファイルを配置：

- `start.mp3`（作業開始時の音声）
- `break.mp3`（休憩開始時の音声）

### ボットの招待

1. [Discord Developer Portal](https://discord.com/developers/applications)にアクセス
2. 新しいアプリケーションを作成
3. ボットセクションでボットを作成
4. 以下の権限を有効化：

   - `applications.commands`
   - `bot`
   - 必要な権限：
     - メッセージの送信
     - 音声接続
     - 音声の再生
     - スラッシュコマンドの使用

5. 生成された招待 URL を使用してボットをサーバーに招待

## 使い方

1. ボットを起動

```bash
python3 bot.py
```

2. Discord で`/pomodoro`コマンドを実行
3. 表示されるボタンから操作：
   - ▶️ 開始ボタン：タイマーを開始
   - ⏹️ 停止ボタン：タイマーを停止

## 注意事項

- ボットを使用するには、ユーザーが音声チャンネルに接続している必要があります
- 音声通知は、ボットが音声チャンネルに接続している場合のみ機能します
- 通知はコマンドを実行したユーザーにのみ表示されます（他のユーザーには見えません）

## ライセンス

sodateya
