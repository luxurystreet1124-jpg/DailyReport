from __future__ import annotations

import json
import logging

import anthropic

from config.settings import settings

logger = logging.getLogger(__name__)

EVENING_SYSTEM_PROMPT = """あなたは日報作成アシスタントです。
提供されるアクティビティデータを基に、その日の業務まとめを自然な日本語で作成してください。

## ルール
- ビジネスメールのようなフォーマルすぎない、自然な日本語で書く
- カテゴリ別に整理する（会議、メール、ドキュメント、コミュニケーションなど）
- 重要な成果や進捗を強調する
- 具体的な固有名詞（プロジェクト名、人名）はそのまま使用する
- Markdown形式で出力する
- アクティビティがない場合は「本日は特記事項なし」と簡潔に書く

## 出力フォーマット
### 本日の業務まとめ

#### 主な業務内容
（メールやSlackのやりとりから判断できる主要な業務を箇条書き）

#### 会議・打ち合わせ
（カレンダーイベントがあれば記載）

#### コミュニケーション
（Slackでの重要なやりとりがあれば記載）

#### ドキュメント作業
（Confluence作業があれば記載）

#### 所感・備考
（全体を通しての一言コメント）
"""

MORNING_SYSTEM_PROMPT = """あなたは業務タスク提案アシスタントです。
前日までのアクティビティデータと本日のカレンダー予定を基に、
当日やるべきタスクを具体的に提案してください。

## ルール
- 前日までのメール・Slack・Confluenceのやりとりから、返信待ち・未完了・フォローアップが必要な事項を洗い出す
- 本日のカレンダー予定から、準備が必要な会議や対応を整理する
- 優先度（高・中・低）をつけてタスクを提案する
- 具体的なアクション（「〇〇さんにメール返信」「△△の資料を準備」など）を書く
- ビジネスメールのようなフォーマルすぎない、自然な日本語で書く
- Markdown形式で出力する

## 出力フォーマット
### 本日のタスク提案

#### 優先度：高
（すぐに対応が必要なタスク。返信待ちのメール、期限の近い作業など）

#### 優先度：中
（今日中に対応したいタスク。フォローアップ、ドキュメント更新など）

#### 優先度：低
（余裕があれば対応するタスク）

#### 本日の予定
（カレンダーから取得した会議・イベント一覧）

#### 前日までの状況サマリー
（前日の活動から把握できる現在の状況を簡潔にまとめる）
"""


MONTHLY_SUMMARY_PROMPT = """あなたは月次レポート作成アシスタントです。
1ヶ月分の日次レポートデータを基に、月間の業務サマリーを自然な日本語で作成してください。

## ルール
- 1ヶ月を俯瞰した視点でまとめる
- 主要なプロジェクト・案件ごとに進捗をまとめる
- 数値で示せるもの（会議数、メール数、ドキュメント数など）は数値を含める
- 特に成果や貢献が大きかった点をハイライトする
- Markdown形式で出力する

## 出力フォーマット
### 月間業務レポート

#### 主要プロジェクト・案件の進捗
（プロジェクトごとの進捗まとめ）

#### 活動サマリー
（会議、メール、Slack、ドキュメント作業の概要と件数）

#### 主な成果・ハイライト
（特筆すべき成果を箇条書き）

#### 課題・懸念事項
（未解決の課題や注意が必要な点）

#### 月間統計
（数値データのまとめ）
"""

MONTHLY_TASK_PROMPT = """あなたは翌月の業務計画アシスタントです。
今月1ヶ月分の日次レポートデータを分析し、翌月に取り組むべきタスクと目標を提案してください。

## ルール
- 今月の未完了事項・継続案件を洗い出す
- 今月のパターンから翌月に注力すべき領域を提案する
- 具体的なアクションアイテムを優先度付きで提案する
- 改善できそうな業務プロセスがあれば提案する
- Markdown形式で出力する

## 出力フォーマット
### 翌月タスク・目標提案

#### 継続・フォローアップ案件
（今月から持ち越す案件・未完了タスク）

#### 優先タスク
（翌月に優先的に取り組むべきタスク）

#### 改善提案
（業務効率化や改善できそうなポイント）

#### 月間目標の提案
（翌月の目標として設定すると良い項目）
"""


class ClaudeClient:

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = "claude-sonnet-4-5-20250929"

    async def generate_report(
        self, activities: list[dict], report_type: str, user_name: str,
        report_date: str = "",
    ) -> str:
        """Generate a Japanese daily report from collected activities."""
        if report_type == "morning":
            system = MORNING_SYSTEM_PROMPT
        elif report_type == "monthly_summary":
            system = MONTHLY_SUMMARY_PROMPT
        elif report_type == "monthly_tasks":
            system = MONTHLY_TASK_PROMPT
        else:
            system = EVENING_SYSTEM_PROMPT

        # Format activities for the prompt
        activities_text = self._format_activities(activities)

        if report_type == "morning":
            user_prompt = f"""以下は{user_name}さんの前日までのアクティビティデータと本日の予定です。
前日までの活動内容を加味して、本日やるべきタスクを提案してください。

## 前日までのアクティビティ + 本日のカレンダー予定
{activities_text}
"""
        elif report_type == "monthly_summary":
            user_prompt = f"""以下は{user_name}さんの{report_date}月の日次レポート一覧です。
月間の業務サマリーを作成してください。

## 月間の日次レポートデータ
{activities_text}
"""
        elif report_type == "monthly_tasks":
            user_prompt = f"""以下は{user_name}さんの{report_date}月の日次レポート一覧です。
今月の活動を分析し、翌月に取り組むべきタスクと目標を提案してください。

## 月間の日次レポートデータ
{activities_text}
"""
        else:
            user_prompt = f"""以下は{user_name}さんの{report_date}のアクティビティデータです。
本日の業務まとめを作成してください。

## アクティビティデータ
{activities_text}
"""

        try:
            max_tokens = 4000 if report_type.startswith("monthly") else 2000
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

    def _format_activities(self, activities: list[dict]) -> str:
        if not activities:
            return "アクティビティなし"

        # 月次レポート用: daily_reportソースがある場合は日次レポート形式で出力
        daily_reports = [a for a in activities if a.get("source") == "daily_report"]
        if daily_reports:
            return self._format_daily_reports(daily_reports)

        sections = {
            "gmail": [],
            "calendar": [],
            "slack": [],
            "confluence": [],
        }

        for a in activities:
            source = a.get("source", "unknown")
            if source in sections:
                sections[source].append(a)

        text_parts = []

        if sections["calendar"]:
            text_parts.append("### カレンダー（会議・予定）")
            for a in sections["calendar"]:
                text_parts.append(f"- {a.get('summary', a.get('title', ''))}")

        if sections["gmail"]:
            text_parts.append("\n### メール")
            for a in sections["gmail"]:
                direction = "送信" if a.get("activity_type") == "email_sent" else "受信"
                text_parts.append(
                    f"- [{direction}] {a.get('title', '')} - {a.get('summary', '')[:100]}"
                )

        if sections["slack"]:
            text_parts.append("\n### Slack")
            for a in sections["slack"]:
                text_parts.append(
                    f"- {a.get('title', '')}: {a.get('summary', '')[:100]}"
                )

        if sections["confluence"]:
            text_parts.append("\n### Confluence")
            for a in sections["confluence"]:
                text_parts.append(f"- {a.get('summary', a.get('title', ''))}")

        return "\n".join(text_parts)

    def _format_daily_reports(self, reports: list[dict]) -> str:
        """月次レポート用: 日次レポートの内容を日付ごとにまとめる。"""
        text_parts = []
        for r in reports:
            report_type = "夕方" if r.get("activity_type") == "evening" else "朝"
            text_parts.append(f"---\n### {r.get('title', '')} [{report_type}]")
            text_parts.append(r.get("summary", "")[:500])
        return "\n\n".join(text_parts)
