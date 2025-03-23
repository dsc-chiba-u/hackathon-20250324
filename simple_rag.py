#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
簡易的なRAG検索スクリプト

【重要】このスクリプトは実装例・参考資料です
=============================================
このスクリプトは特定のインデックス構造を前提としており、そのままでは実働しません。
Azure APIの呼び出し方法や、RAG実装の参考資料としてご利用ください。
実際に使用する場合は、ご自身の環境や検索インデックスに合わせた調整が必要です。

RAG（Retrieval-Augmented Generation）とは：
RAGは「検索拡張生成」と呼ばれる手法で、大規模言語モデル（LLM）の回答生成能力と
外部知識源からの情報検索を組み合わせたものです。この手法により：
1. 最新情報への対応: トレーニングデータ以降の情報を扱える
2. 幻覚の低減: 外部ソースからの正確な情報に基づいて回答を生成
3. カスタム情報の利用: 特定のドメイン知識を活用した回答が可能

基本的な流れ：
1. ユーザークエリを受け取る
2. クエリに基づいて関連ドキュメントを検索（Retrieval）
3. 検索結果を言語モデルへのコンテキストとして提供
4. 言語モデルが検索結果を基に回答を生成（Generation）

参考：
- Microsoft RAG パターン: https://learn.microsoft.com/ja-jp/azure/search/retrieval-augmented-generation-overview
- Azure AI Search ドキュメント: https://learn.microsoft.com/ja-jp/azure/search/
- Azure OpenAI Service ドキュメント: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/
"""

import os
import sys
import json
import argparse
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

# 環境変数の読み込み
# .envファイルから API キーなどの環境変数を読み込みます
# 必要な環境変数:
# - AZURE_SEARCH_ENDPOINT: Azure AI Search のエンドポイントURL
# - AZURE_SEARCH_ADMIN_KEY: Azure AI Search の管理キー
# - AZURE_OPENAI_ENDPOINT: Azure OpenAI の エンドポイントURL
# - AZURE_OPENAI_KEY: Azure OpenAI のAPIキー
# - AZURE_OPENAI_CHAT_DEPLOYMENT: デプロイしたモデルの名前
load_dotenv()

def search_documents(query, index_name, top=5):
    """
    Azure AI Searchでドキュメントを検索する
    
    Azure AI Searchは、フルテキスト検索、ファセット検索、フィルタリングなどの
    高度な検索機能を提供するマネージドサービスです。
    
    API使用方法：
    1. SearchClientオブジェクトを作成して検索エンドポイントに接続
    2. search()メソッドでクエリを実行
    3. 検索結果を処理
    
    参考：
    - クイックスタート: https://learn.microsoft.com/ja-jp/azure/search/search-get-started-python
    - Python SDK: https://learn.microsoft.com/ja-jp/python/api/overview/azure/search-documents-readme
    
    Parameters:
        query (str): 検索するテキスト
        index_name (str): 検索するインデックス名
        top (int): 返す検索結果の最大数
        
    Returns:
        dict: 検索結果数と検索されたドキュメントのリスト
    """
    # Azure AI Search接続情報
    search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    search_key = os.environ["AZURE_SEARCH_ADMIN_KEY"]
    
    # 検索クライアントの作成
    # AzureKeyCredentialはAzure SDKで認証に使用される共通クラス
    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(search_key)
    )
    
    # 検索の実行
    # search_fields: どのフィールドを検索対象とするか指定
    # include_total_count: 合計結果数を含めるかどうか
    # top: 返す結果の最大数
    search_results = search_client.search(
        search_text=query,
        search_fields=["name", "description", "category", "brand"],
        include_total_count=True,
        top=top
    )
    
    # 検索結果をリストに変換（メタデータフィールドを除外）
    documents = []
    for result in search_results:
        doc = {k: v for k, v in result.items() if not k.startswith('@')}
        documents.append(doc)
    
    return {
        "count": search_results.get_count(),
        "documents": documents
    }

def generate_answer(question, documents):
    """
    OpenAIを使って回答を生成する
    
    RAGの「Generation」部分を担当する関数です。検索で取得したドキュメントを
    コンテキストとして言語モデルに提供し、質問に対する回答を生成します。
    
    Azure OpenAI Serviceは、Microsoft Azureが提供するOpenAIモデルの
    マネージドサービスです。GPT-4、GPT-3.5などのモデルを安全に利用できます。
    
    API使用方法：
    1. AzureOpenAIクライアントを作成
    2. システムメッセージとユーザーメッセージを設定
    3. chat.completions.createでリクエストを送信
    
    参考：
    - クイックスタート: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/chatgpt-quickstart
    - Python SDK: https://learn.microsoft.com/ja-jp/python/api/openai/openai.azureopenai
    - プロンプトエンジニアリング: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/concepts/prompt-engineering
    
    Parameters:
        question (str): ユーザーの質問
        documents (list): 検索結果のドキュメントリスト
        
    Returns:
        str: 生成された回答テキスト
    """
    try:
        # Azure OpenAI接続情報
        openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        openai_api_key = os.environ["AZURE_OPENAI_KEY"]
        deployment_name = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]
        
        # OpenAIクライアントの作成
        # API バージョンは定期的に更新されるため、最新のものを確認することをお勧めします
        # https://learn.microsoft.com/ja-jp/azure/ai-services/openai/reference#rest-api-versioning
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=openai_api_key,
            api_version="2024-02-15-preview",
            azure_endpoint=openai_endpoint
        )
        
        # 文脈の作成
        # 検索結果をLLMに提供するコンテキストとして整形
        # これがRAGの重要な部分で、外部知識をLLMに注入します
        context = ""
        for i, doc in enumerate(documents, 1):
            context += f"\n--- 商品 {i} ---\n"
            context += f"商品名: {doc.get('name', '')}\n"
            context += f"価格: ${doc.get('price', '')}\n"
            context += f"カテゴリ: {doc.get('category', '')}\n"
            context += f"ブランド: {doc.get('brand', '')}\n"
            description = doc.get("description", "")
            # 長い場合は切り詰める
            if len(description) > 1000:
                description = description[:1000] + "..."
            context += f"説明: {description}\n"
        
        # プロンプトの作成
        # システムメッセージでAIの役割と制約を設定
        # RAGでは「与えられた情報源のみを使用」という制約が重要
        system_message = f"""
あなたは親切なアシスタントです。
以下の情報源のみを使用して、ユーザーの質問に簡潔に答えてください。
情報源に記載されていない場合は、「情報が見つかりませんでした」と伝えてください。
回答は日本語で提供してください。

情報源:
{context}
"""
        
        # OpenAIによる回答生成
        # パラメータ説明:
        # - model: デプロイされたモデル名
        # - messages: システムメッセージとユーザーメッセージ
        # - temperature: 生成のランダム性（0=決定的、1=創造的）
        # - max_tokens: 生成する最大トークン数
        response = client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": question}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"OpenAIでの回答生成に失敗しました: {str(e)}\n\n以下に検索結果を表示します。"

def main():
    """
    メイン処理関数
    
    コマンドライン引数を解析し、検索と回答生成を実行します。
    このスクリプトは以下の手順でRAGを実装しています：
    1. ユーザーのクエリを受け取る
    2. Azure AI Searchで関連ドキュメントを検索
    3. 検索結果があればAzure OpenAIで回答を生成
    
    コマンドライン使用例:
    ```
    # 基本的な使用方法
    python simple_rag.py --query "ノートパソコンのおすすめは？"
    
    # 詳細情報を表示
    python simple_rag.py --query "ノートパソコンのおすすめは？" --verbose
    
    # カスタムインデックスを指定
    python simple_rag.py --query "ノートパソコンのおすすめは？" --index "my-index"
    
    # 検索結果のみ表示（回答生成なし）
    python simple_rag.py --query "ノートパソコンのおすすめは？" --search-only
    ```
    """
    # コマンドライン引数の解析
    parser = argparse.ArgumentParser(description="簡易的なRAG検索")
    parser.add_argument("--query", "-q", type=str, required=True, help="検索クエリ")
    parser.add_argument("--index", "-i", type=str, default="unifyd-docs-index", help="インデックス名")
    parser.add_argument("--top", "-t", type=int, default=3, help="検索結果の最大数")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細情報を表示")
    parser.add_argument("--search-only", "-s", action="store_true", help="検索のみ実行")
    args = parser.parse_args()
    
    # 検索の実行
    search_results = search_documents(args.query, args.index, args.top)
    
    # 検索結果の表示
    print(f"検索クエリ: {args.query}")
    print(f"検索結果: {search_results['count']} 件\n")
    
    # 詳細表示
    for i, doc in enumerate(search_results["documents"], 1):
        print(f"--- ドキュメント {i} ---")
        print(f"商品名: {doc.get('name', 'N/A')}")
        print(f"価格: ${doc.get('price', 'N/A')}")
        print(f"カテゴリ: {doc.get('category', 'N/A')}")
        print(f"ブランド: {doc.get('brand', 'N/A')}")
        description = doc.get("description", "")
        if not args.verbose and len(description) > 300:
            description = description[:300] + "..."
        print(f"説明: {description}\n")
    
    # ドキュメントがある場合、かつsearch_onlyでない場合は回答を生成
    if search_results["documents"] and not args.search_only:
        print("=== 生成された回答 ===")
        answer = generate_answer(args.query, search_results["documents"])
        print(answer)
    elif not search_results["documents"]:
        print("関連するドキュメントが見つかりませんでした。")

if __name__ == "__main__":
    main() 