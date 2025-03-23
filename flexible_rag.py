#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
flexible_rag.py - 汎用的なRAG検索スクリプト

異なる構造のAzure AI Searchインデックスに対応し、
動的にフィールド情報を取得して検索を行います。

【実運用可能なスクリプト】
このスクリプトは様々なインデックス構造に対応する実用的なRAG実装です。
インデックスのスキーマを自動的に解析し、利用可能なフィールドを動的に特定して検索を行います。

RAG（Retrieval-Augmented Generation）について:
===========================================
RAGは大規模言語モデル（LLM）の応答生成能力と外部知識検索を組み合わせた手法です。
- 検索（Retrieval）: ユーザーのクエリに基づき、関連情報をデータベースから検索
- 生成（Generation）: 検索結果をコンテキストとしてLLMに提供し、回答を生成

この手法の主なメリット:
1. 最新データへのアクセス: トレーニングデータ以降の新しい情報を利用可能
2. ドメイン特化: 特定分野の専門知識を活用した応答が可能
3. 情報の正確性向上: 外部ソースからの事実に基づいた回答を提供
4. 幻覚の低減: 根拠に基づいた回答生成で誤情報を減少

このスクリプトの特長:
==================
- 柔軟性: どのようなインデックス構造にも対応できるよう設計
- 自動検出: 検索可能・取得可能なフィールドを自動的に特定
- インタラクティブモード: コマンドライン引数なしでの対話的操作をサポート
- 詳細な制御: 生成パラメータやフィールド表示などの細かい設定が可能

必要な環境変数:
============
環境変数ファイル(.env)に以下の情報を設定する必要があります:
- AZURE_SEARCH_ENDPOINT: Azure AI Searchのエンドポイント
- AZURE_SEARCH_ADMIN_KEY: 検索サービスの管理キー
- AZURE_OPENAI_ENDPOINT: Azure OpenAI Serviceのエンドポイント
- AZURE_OPENAI_API_KEY: OpenAIのAPIキー
- AZURE_OPENAI_CHAT_DEPLOYMENT: デプロイされたモデル名

使用例:
=====
# インデックス一覧の表示
python flexible_rag.py --env-file .env --list-indexes

# 特定インデックスのスキーマ表示
python flexible_rag.py --env-file .env --index "my-index" --schema

# 検索の実行
python flexible_rag.py --env-file .env --index "my-index" --query "検索したい内容"

# 詳細表示モード
python flexible_rag.py --env-file .env --index "my-index" --query "検索したい内容" --verbose

# 検索のみ実行（回答生成なし）
python flexible_rag.py --env-file .env --index "my-index" --query "検索したい内容" --search-only

参考ドキュメント:
==============
- RAGパターン: https://learn.microsoft.com/ja-jp/azure/search/retrieval-augmented-generation-overview
- Azure AI Search: https://learn.microsoft.com/ja-jp/azure/search/
- Azure OpenAI: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/
- インデックスの定義: https://learn.microsoft.com/ja-jp/azure/search/search-what-is-an-index
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from dotenv import load_dotenv
import time

# Azure SDK
from azure.identity import AzureCliCredential, DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex

# 環境変数の読み込み
def load_environment_variables(env_path: str):
    """
    指定されたパスから環境変数を読み込む
    
    Azure APIを使用するために必要な認証情報や設定を.envファイルから読み込みます。
    必須の環境変数がすべて設定されているかチェックし、不足があればエラーメッセージを表示します。
    
    Parameters:
        env_path (str): 環境変数ファイル(.env)のパス
        
    Returns:
        bool: 環境変数の読み込みに成功した場合はTrue、失敗した場合はFalse
    """
    # パスのオブジェクトを作成
    env_file = Path(env_path)
    
    # ファイルが存在するか確認
    if not env_file.exists():
        print(f"エラー: 環境変数ファイル '{env_path}' が見つかりません。")
        return False
    
    # 環境変数を読み込む
    load_dotenv(env_file)
    
    # 必須環境変数の確認
    required_vars = [
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_ADMIN_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_CHAT_DEPLOYMENT"
    ]
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"エラー: 以下の環境変数が設定されていません: {', '.join(missing_vars)}")
        return False
    
    return True

# Azure認証情報の取得
def get_azure_credentials():
    """
    Azure認証情報を取得する
    
    Azure APIにアクセスするための認証情報を取得します。
    まずAzure CLIの認証情報を試し、失敗した場合は環境変数から取得したAPIキーを使用します。
    
    Azure認証には主に2つの方法があります:
    1. AzureCliCredential: Azureコマンドラインツールのログイン情報を使用（開発環境向け）
    2. AzureKeyCredential: APIキーを直接使用する方法（本番環境向け）
    
    Reference:
    - Azure Authentication Library: https://learn.microsoft.com/ja-jp/python/api/overview/azure/identity-readme
    
    Returns:
        AzureCliCredential または AzureKeyCredential: 認証に成功した場合は認証オブジェクト
        None: 両方の認証方法が失敗した場合
    """
    try:
        # Azure CLI認証
        credential = AzureCliCredential()
        # 認証情報をテスト
        token = credential.get_token("https://management.azure.com/.default")
        return credential
    except Exception as e:
        print(f"Azure CLI認証に失敗しました: {str(e)}")
        print("代替認証方法を試行中...")
        
        try:
            # 環境変数から取得した認証情報を使用
            credential = AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"])
            return credential
        except Exception as e2:
            print(f"代替認証にも失敗しました: {str(e2)}")
            print("Azure CLIで'az login'を実行してログインしてください。")
            return None

# インデックス一覧の取得
def list_search_indexes(credential) -> List[str]:
    """
    利用可能なインデックスの一覧を取得する
    
    Azure AI Searchサービスに存在するすべての検索インデックスの名前を取得します。
    
    Azure AI Searchは、検索可能なコンテンツのコンテナである「インデックス」を管理します。
    インデックスは、データベースのテーブルに似た構造を持ち、ドキュメントとフィールドから構成されます。
    
    API使用方法:
    1. SearchIndexClientオブジェクトを作成
    2. list_indexes()メソッドで利用可能なインデックスを取得
    
    参考:
    - インデックス管理: https://learn.microsoft.com/ja-jp/azure/search/search-how-to-manage-indexes
    - Python SDK: https://learn.microsoft.com/ja-jp/python/api/azure-search-documents/azure.search.documents.indexes.searchindexclient
    
    Parameters:
        credential: Azure認証情報（AzureCliCredentialまたはAzureKeyCredential）
        
    Returns:
        List[str]: インデックス名のリスト。失敗した場合は空のリスト
    """
    try:
        search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        
        # SearchIndexClientの作成
        if isinstance(credential, AzureKeyCredential):
            index_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=credential
            )
        else:
            # API Keyを使用
            index_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"])
            )
        
        # インデックス一覧の取得
        result = list(index_client.list_indexes())
        return [index.name for index in result]
    except Exception as e:
        print(f"インデックス一覧の取得に失敗しました: {str(e)}")
        return []

# インデックス情報の取得
def get_index_schema(index_name: str, credential) -> Optional[Dict]:
    """
    インデックスのスキーマ情報を取得する
    
    指定されたインデックスの詳細なスキーマ情報（フィールド名、型、検索可能性など）を取得します。
    
    このRAGシステムの柔軟性を支える重要な関数です。任意のインデックス構造を解析し、
    検索可能なフィールドと取得可能なフィールドを特定することで、
    インデックスの構造に応じた適切な検索と結果表示を可能にします。
    
    スキーマ分析のポイント:
    - 検索可能(searchable)フィールド: 全文検索の対象となるフィールド
    - 取得可能(retrievable)フィールド: 検索結果として返されるフィールド
    - キー(key)フィールド: ドキュメントを一意に識別するフィールド
    - ベクトル(vector)フィールド: ベクトル検索用のフィールド（存在する場合）
    
    参考:
    - フィールド属性: https://learn.microsoft.com/ja-jp/azure/search/search-what-is-an-index#field-attributes
    - インデックス定義: https://learn.microsoft.com/ja-jp/azure/search/search-how-to-create-search-index
    
    Parameters:
        index_name (str): スキーマ情報を取得するインデックスの名前
        credential: Azure認証情報
        
    Returns:
        Optional[Dict]: インデックスのスキーマ情報を含む辞書。失敗した場合はNone
    """
    try:
        search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        
        # SearchIndexClientの作成
        if isinstance(credential, AzureKeyCredential):
            index_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=credential
            )
        else:
            # API Keyを使用
            index_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"])
            )
        
        # インデックス情報の取得
        index = index_client.get_index(index_name)
        
        # スキーマ情報の抽出
        schema = {
            "name": index.name,
            "fields": [],
            "searchable_fields": [],
            "retrievable_fields": [],
            "has_vector_fields": False
        }
        
        for field in index.fields:
            # プロパティの存在を確認してから取得
            field_info = {
                "name": field.name,
                "type": str(field.type),
                "searchable": hasattr(field, "searchable") and field.searchable,
                "retrievable": hasattr(field, "retrievable") and field.retrievable,
                "filterable": hasattr(field, "filterable") and field.filterable,
                "sortable": hasattr(field, "sortable") and field.sortable,
                "facetable": hasattr(field, "facetable") and field.facetable,
                "key": hasattr(field, "key") and field.key
            }
            
            # 代替のプロパティ名を確認
            if not field_info["searchable"] and hasattr(field, "is_searchable"):
                field_info["searchable"] = field.is_searchable
            if not field_info["retrievable"] and hasattr(field, "is_retrievable"):
                field_info["retrievable"] = field.is_retrievable
            if not field_info["filterable"] and hasattr(field, "is_filterable"):
                field_info["filterable"] = field.is_filterable
            if not field_info["sortable"] and hasattr(field, "is_sortable"):
                field_info["sortable"] = field.is_sortable
            if not field_info["facetable"] and hasattr(field, "is_facetable"):
                field_info["facetable"] = field.is_facetable
            if not field_info["key"] and hasattr(field, "is_key"):
                field_info["key"] = field.is_key
            
            if hasattr(field, "vector_search_dimensions") and field.vector_search_dimensions:
                field_info["vector_search_dimensions"] = field.vector_search_dimensions
                schema["has_vector_fields"] = True
            
            schema["fields"].append(field_info)
            
            # always add to retrievable_fields by default
            schema["retrievable_fields"].append(field.name)
            
            if field_info["searchable"]:
                schema["searchable_fields"].append(field.name)
        
        return schema
    except Exception as e:
        print(f"インデックス '{index_name}' の情報取得に失敗しました: {str(e)}")
        return None

# ドキュメント検索
def search_documents(query: str, index_name: str, schema: Dict, credential, top: int = 5, vector_exclude_pattern: str = "vector", vector_type_pattern: str = "Collection(Edm.Single)") -> Dict:
    """
    指定されたインデックスでドキュメントを検索する
    
    ユーザーのクエリに基づいて、インデックスから関連ドキュメントを検索します。
    インデックスのスキーマ情報を利用して、検索可能なフィールドを動的に特定し、
    適切なフィールドに対して検索を実行します。
    
    この関数はRAGの「Retrieval（検索）」部分を担当し、インデックスの構造に依存せず
    適切な検索を行える柔軟性が特徴です。異なるインデックスに対しても、
    動的に検索可能フィールドを特定するため、汎用的に使用できます。
    
    ベクトル検索フィールドの除外:
    ベクトルフィールドは通常のテキスト検索に適さないため、フィールド名や型に基づいて
    自動的に除外されます。ベクトルフィールドの識別パターンはパラメータで調整可能です。
    
    API使用方法:
    1. SearchClientオブジェクトを作成
    2. スキーマから検索可能なフィールドを特定
    3. search()メソッドでクエリを実行
    4. 検索結果をメタデータを除去して整形
    
    参考:
    - 検索の基本: https://learn.microsoft.com/ja-jp/azure/search/search-query-overview
    - 検索構文: https://learn.microsoft.com/ja-jp/azure/search/query-simple-syntax
    - Python SDK: https://learn.microsoft.com/ja-jp/python/api/azure-search-documents/azure.search.documents.searchclient
    
    Parameters:
        query (str): 検索クエリ
        index_name (str): 検索対象のインデックス名
        schema (Dict): インデックスのスキーマ情報
        credential: Azure認証情報
        top (int): 返す検索結果の最大数
        vector_exclude_pattern (str): ベクトルフィールドを除外するための名前パターン
        vector_type_pattern (str): ベクトルフィールドの型パターン
        
    Returns:
        Dict: 検索結果数とドキュメントのリストを含む辞書
    """
    try:
        search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        
        # SearchClientの作成
        if isinstance(credential, AzureKeyCredential):
            search_client = SearchClient(
                endpoint=search_endpoint,
                index_name=index_name,
                credential=credential
            )
        else:
            # API Keyを使用
            search_client = SearchClient(
                endpoint=search_endpoint,
                index_name=index_name,
                credential=AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"])
            )
        
        # 検索可能なフィールドの取得（ベクトルフィールドを除外）
        searchable_fields = []
        for field in schema["fields"]:
            if field["searchable"] and vector_exclude_pattern.lower() not in field["name"].lower() and not field["type"].startswith(vector_type_pattern):
                searchable_fields.append(field["name"])
        
        if not searchable_fields:
            print("警告: 検索可能なテキストフィールドが見つかりません。すべてのフィールドで検索します。")
            search_results = search_client.search(
                search_text=query,
                include_total_count=True,
                top=top
            )
        else:
            print(f"検索フィールド: {', '.join(searchable_fields)}")
            # 検索の実行
            search_results = search_client.search(
                search_text=query,
                search_fields=searchable_fields,
                include_total_count=True,
                top=top
            )
        
        # 結果の整形
        documents = []
        for result in search_results:
            doc = {k: v for k, v in result.items() if not k.startswith('@')}
            documents.append(doc)
        
        return {
            "count": search_results.get_count(),
            "documents": documents
        }
    except Exception as e:
        print(f"検索に失敗しました: {str(e)}")
        return {"count": 0, "documents": []}

# 回答生成
def generate_answer(question: str, documents: List[Dict], schema: Dict, max_context_length: int = 1000, temperature: float = 0.7, max_tokens: int = 500) -> str:
    """
    検索結果に基づいて回答を生成する
    
    RAGの「Generation（生成）」部分を担当する関数です。検索で取得したドキュメントを
    コンテキストとして言語モデルに提供し、質問に対する回答を生成します。
    
    この関数の特徴:
    1. 動的フィールド処理: インデックスの構造に関わらず適切にコンテキストを構築
    2. スマートな要約: 長いテキストフィールドを自動的に要約して適切なサイズに調整
    3. 構造化データ対応: リストや辞書などの構造化データも適切に処理
    4. 人間可読なフォーマット: フィールド名を読みやすい形式に変換
    
    Azure OpenAI Service API使用方法:
    1. AzureOpenAIクライアントを作成
    2. 検索結果からコンテキストを構築
    3. システムメッセージとユーザーメッセージを設定
    4. chat.completions.createでリクエストを送信
    
    参考:
    - Azure OpenAI Service: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/
    - チャット補完API: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/how-to/chatgpt
    - プロンプト設計: https://learn.microsoft.com/ja-jp/azure/ai-services/openai/concepts/prompt-engineering
    
    Parameters:
        question (str): ユーザーの質問
        documents (List[Dict]): 検索結果のドキュメントリスト
        schema (Dict): インデックスのスキーマ情報
        max_context_length (int): 各フィールドの最大コンテキスト長
        temperature (float): 生成の温度パラメータ（0.0-1.0）
        max_tokens (int): 生成する最大トークン数
        
    Returns:
        str: 生成された回答。エラーの場合はエラーメッセージ
    """
    try:
        # Azure OpenAI接続情報
        openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        openai_api_key = os.environ["AZURE_OPENAI_API_KEY"]
        deployment_name = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]
        
        # OpenAIクライアントの作成
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=openai_api_key,
            api_version="2024-02-15-preview",
            azure_endpoint=openai_endpoint
        )
        
        # 取得可能なフィールドの抽出
        retrievable_fields = schema["retrievable_fields"]
        
        # 文脈の作成
        context = ""
        for i, doc in enumerate(documents, 1):
            context += f"\n--- ドキュメント {i} ---\n"
            
            # すべての取得可能なフィールドを表示
            for field_name in retrievable_fields:
                if field_name in doc:
                    value = doc[field_name]
                    
                    # 長いテキストの場合は切り詰める
                    if isinstance(value, str) and len(value) > max_context_length:
                        value = value[:max_context_length] + "..."
                    
                    # リストや辞書の場合はJSON形式に変換
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value, ensure_ascii=False)
                    
                    # フィールド名を人間が読みやすい形式に変換
                    display_name = field_name.replace("_", " ").capitalize()
                    context += f"{display_name}: {value}\n"
        
        # プロンプトの作成
        # このプロンプト設計は以下のポイントを重視:
        # 1. 明確な役割定義: アシスタントの役割と応答範囲を明示
        # 2. 緩やかな制約: 直接関連する情報がなくても関連推測を許可
        # 3. クオリティ指示: 簡潔さと正確性を強調
        system_message = f"""
あなたは知識豊富なアシスタントです。
以下の情報源を参考にして、ユーザーの質問に対して有益な回答を提供してください。
情報源に直接関連する内容が見つからない場合でも、情報源から推測できる関連情報があれば提供してください。
完全に情報がない場合のみ「情報が見つかりませんでした」と伝えてください。
回答は日本語で提供し、簡潔かつ正確であることを心がけてください。

質問: {question}

情報源:
{context}
"""
        
        # OpenAIによる回答生成
        # パラメータの説明:
        # - model: デプロイされたモデル名
        # - messages: 会話履歴（システムメッセージとユーザーメッセージ）
        # - temperature: 出力のランダム性（0=決定的、1=創造的）
        # - max_tokens: 生成する最大トークン数
        response = client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": "この情報から何がわかりますか？"}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"OpenAIでの回答生成に失敗しました: {str(e)}\n\n以下に検索結果を表示します。"

def display_documents(documents: List[Dict], schema: Dict, verbose: bool = False, summary_length: int = 300) -> None:
    """
    検索結果のドキュメントを表示する
    
    検索結果のドキュメントを人間可読な形式で表示します。
    インデックスの構造に関わらず、すべての取得可能なフィールドを適切に表示します。
    
    表示の特徴:
    1. 動的フィールド表示: スキーマ情報に基づいて取得可能なフィールドを表示
    2. 長文の自動要約: 長いテキストフィールドを適切に要約（verbose=Falseの場合）
    3. 構造化データの整形: リストや辞書などの構造化データをJSON形式で表示
    4. 読みやすいフィールド名: スネークケースのフィールド名を自然な表示名に変換
    
    Parameters:
        documents (List[Dict]): 表示するドキュメントのリスト
        schema (Dict): インデックスのスキーマ情報
        verbose (bool): 詳細表示モードかどうか。Trueなら全テキストを表示
        summary_length (int): 要約時の最大文字数
    """
    retrievable_fields = schema["retrievable_fields"]
    
    for i, doc in enumerate(documents, 1):
        print(f"--- ドキュメント {i} ---")
        
        # すべての取得可能なフィールドを表示
        for field_name in retrievable_fields:
            if field_name in doc:
                value = doc[field_name]
                
                # 長いテキストの場合は切り詰める
                if isinstance(value, str) and not verbose and len(value) > summary_length:
                    value = value[:summary_length] + "..."
                
                # リストや辞書の場合はJSON形式に変換
                if isinstance(value, (list, dict)):
                    value_json = json.dumps(value, ensure_ascii=False)
                    if not verbose and len(value_json) > summary_length:
                        value = value_json[:summary_length] + "..."
                    else:
                        value = value_json
                
                # フィールド名を人間が読みやすい形式に変換
                display_name = field_name.replace("_", " ").capitalize()
                print(f"{display_name}: {value}")
        
        print()

def main():
    """
    メイン処理関数
    
    コマンドライン引数を解析し、RAGシステムの各機能を実行します。
    
    このRAGシステムの特徴的な機能:
    1. 対話的操作: 引数が指定されていない場合、インタラクティブモードで操作できる
    2. インデックス探索: 利用可能なインデックスの一覧表示とスキーマ確認
    3. 柔軟な検索: 様々なインデックス構造に対応した検索機能
    4. 詳細な制御: パラメータによる生成プロセスのカスタマイズ
    
    実行フロー:
    1. コマンドライン引数を解析
    2. 環境変数を読み込み、Azure認証情報を取得
    3. コマンドに応じて以下の処理を実行:
       - インデックス一覧の表示
       - スキーマ情報の表示
       - ドキュメントの検索と表示
       - 検索結果に基づく回答の生成
    
    使用例については冒頭のドキュメント文字列を参照してください。
    """
    # コマンドライン引数の解析
    parser = argparse.ArgumentParser(description="汎用的なRAG検索")
    # 必須オプション
    parser.add_argument("--env-file", "-e", type=str, required=True, help="環境変数ファイルのパス（必須）")
    
    # 基本的な検索オプション
    parser.add_argument("--query", "-q", type=str, help="検索クエリ")
    parser.add_argument("--index", "-i", type=str, help="インデックス名")
    parser.add_argument("--list-indexes", "-l", action="store_true", help="インデックス一覧を表示")
    parser.add_argument("--schema", "-s", action="store_true", help="インデックスのスキーマを表示")
    parser.add_argument("--all-schemas", "-a", action="store_true", help="すべてのインデックスのスキーマを表示")
    parser.add_argument("--top", "-t", type=int, default=3, help="検索結果の最大数")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細情報を表示")
    parser.add_argument("--search-only", "-so", action="store_true", help="検索のみ実行")
    
    # 追加の詳細オプション
    parser.add_argument("--temperature", type=float, default=0.7, help="生成モデルの温度（0.0～1.0）")
    parser.add_argument("--max-tokens", type=int, default=500, help="生成される最大トークン数")
    parser.add_argument("--max-context-length", type=int, default=1000, help="コンテキストフィールドの最大長")
    parser.add_argument("--summary-length", type=int, default=300, help="表示時のテキスト要約長")
    parser.add_argument("--vector-exclude", type=str, default="vector", help="検索から除外するベクトルフィールドのパターン")
    parser.add_argument("--vector-type", type=str, default="Collection(Edm.Single)", help="ベクトル型のパターン")
    
    args = parser.parse_args()
    
    # 環境変数の読み込み
    if not load_environment_variables(args.env_file):
        return
    
    # Azure認証情報の取得
    credential = get_azure_credentials()
    if not credential:
        return
    
    # すべてのインデックスのスキーマを表示
    if args.all_schemas:
        print("すべてのインデックスのスキーマ情報を取得中...")
        indexes = list_search_indexes(credential)
        if not indexes:
            print("インデックスが見つかりませんでした。")
            return
            
        for index_name in indexes:
            schema = get_index_schema(index_name, credential)
            if schema:
                print(f"\n===== インデックス: {index_name} =====")
                print(f"検索可能なフィールド: {', '.join(schema['searchable_fields'])}")
                print(f"取得可能なフィールド: {', '.join(schema['retrievable_fields'])}")
                print("\nフィールド詳細:")
                for field in schema["fields"]:
                    print(f"- {field['name']}: {field['type']}, searchable={field['searchable']}, retrievable={field['retrievable']}")
        return
    
    # インデックス一覧の表示
    if args.list_indexes:
        print("利用可能なインデックス一覧:")
        indexes = list_search_indexes(credential)
        for i, index_name in enumerate(indexes, 1):
            print(f"{i}. {index_name}")
        return
    
    # インデックスが指定されていない場合
    if not args.index and not args.query:
        # インデックス一覧を表示
        print("利用可能なインデックス一覧:")
        indexes = list_search_indexes(credential)
        for i, index_name in enumerate(indexes, 1):
            print(f"{i}. {index_name}")
        
        # インデックスの選択
        while True:
            try:
                choice = input("\nインデックスを選択してください (番号): ")
                index_idx = int(choice) - 1
                if 0 <= index_idx < len(indexes):
                    selected_index = indexes[index_idx]
                    break
                else:
                    print(f"1から{len(indexes)}の範囲で選択してください。")
            except ValueError:
                print("数値を入力してください。")
        
        # スキーマの取得
        schema = get_index_schema(selected_index, credential)
        
        # スキーマのみ表示する場合
        if args.schema:
            print(f"\nインデックス '{selected_index}' のスキーマ情報:")
            print(f"検索可能なフィールド: {', '.join(schema['searchable_fields'])}")
            print(f"取得可能なフィールド: {', '.join(schema['retrievable_fields'])}")
            print("\nフィールド詳細:")
            for field in schema["fields"]:
                print(f"- {field['name']}: {field['type']}, searchable={field['searchable']}, retrievable={field['retrievable']}")
            return
        
        # 検索クエリの入力
        query = input("\n検索クエリを入力してください: ")
        
        # 検索の実行
        search_results = search_documents(
            query, 
            selected_index, 
            schema, 
            credential, 
            args.top, 
            args.vector_exclude, 
            args.vector_type
        )
        
        # 検索結果の表示
        print(f"\n検索クエリ: {query}")
        print(f"検索結果: {search_results['count']} 件\n")
        
        # ドキュメントの表示
        display_documents(search_results["documents"], schema, args.verbose, args.summary_length)
        
        # ドキュメントがある場合、かつsearch_onlyでない場合は回答を生成
        if search_results["documents"] and not args.search_only:
            print("=== 生成された回答 ===")
            answer = generate_answer(
                query, 
                search_results["documents"], 
                schema, 
                args.max_context_length, 
                args.temperature, 
                args.max_tokens
            )
            print(answer)
        elif not search_results["documents"]:
            print("関連するドキュメントが見つかりませんでした。")
    
    # インデックスと検索クエリが指定されている場合
    elif args.index and args.query:
        # スキーマの取得
        schema = get_index_schema(args.index, credential)
        if not schema:
            return
        
        # スキーマのみ表示する場合
        if args.schema:
            print(f"\nインデックス '{args.index}' のスキーマ情報:")
            print(f"検索可能なフィールド: {', '.join(schema['searchable_fields'])}")
            print(f"取得可能なフィールド: {', '.join(schema['retrievable_fields'])}")
            print("\nフィールド詳細:")
            for field in schema["fields"]:
                print(f"- {field['name']}: {field['type']}, searchable={field['searchable']}, retrievable={field['retrievable']}")
            return
        
        # 検索の実行
        search_results = search_documents(
            args.query, 
            args.index, 
            schema, 
            credential, 
            args.top, 
            args.vector_exclude, 
            args.vector_type
        )
        
        # 検索結果の表示
        print(f"\n検索クエリ: {args.query}")
        print(f"検索結果: {search_results['count']} 件\n")
        
        # ドキュメントの表示
        display_documents(search_results["documents"], schema, args.verbose, args.summary_length)
        
        # ドキュメントがある場合、かつsearch_onlyでない場合は回答を生成
        if search_results["documents"] and not args.search_only:
            print("=== 生成された回答 ===")
            answer = generate_answer(
                args.query, 
                search_results["documents"], 
                schema, 
                args.max_context_length, 
                args.temperature, 
                args.max_tokens
            )
            print(answer)
        elif not search_results["documents"]:
            print("関連するドキュメントが見つかりませんでした。")
    
    # インデックスのみ指定されている場合
    elif args.index:
        # スキーマの取得
        schema = get_index_schema(args.index, credential)
        if not schema:
            return
        
        # スキーマを表示
        if args.schema:
            print(f"\nインデックス '{args.index}' のスキーマ情報:")
            print(f"検索可能なフィールド: {', '.join(schema['searchable_fields'])}")
            print(f"取得可能なフィールド: {', '.join(schema['retrievable_fields'])}")
            print("\nフィールド詳細:")
            for field in schema["fields"]:
                print(f"- {field['name']}: {field['type']}, searchable={field['searchable']}, retrievable={field['retrievable']}")
            return
        
        # 検索クエリの入力
        query = input("検索クエリを入力してください: ")
        
        # 検索の実行
        search_results = search_documents(
            query, 
            args.index, 
            schema, 
            credential, 
            args.top, 
            args.vector_exclude, 
            args.vector_type
        )
        
        # 検索結果の表示
        print(f"\n検索クエリ: {query}")
        print(f"検索結果: {search_results['count']} 件\n")
        
        # ドキュメントの表示
        display_documents(search_results["documents"], schema, args.verbose, args.summary_length)
        
        # ドキュメントがある場合、かつsearch_onlyでない場合は回答を生成
        if search_results["documents"] and not args.search_only:
            print("=== 生成された回答 ===")
            answer = generate_answer(
                query, 
                search_results["documents"], 
                schema, 
                args.max_context_length, 
                args.temperature, 
                args.max_tokens
            )
            print(answer)
        elif not search_results["documents"]:
            print("関連するドキュメントが見つかりませんでした。")
    
    # 検索クエリのみ指定されている場合
    elif args.query:
        # インデックス一覧を表示
        print("利用可能なインデックス一覧:")
        indexes = list_search_indexes(credential)
        for i, index_name in enumerate(indexes, 1):
            print(f"{i}. {index_name}")
        
        # インデックスの選択
        while True:
            try:
                choice = input("\nインデックスを選択してください (番号): ")
                index_idx = int(choice) - 1
                if 0 <= index_idx < len(indexes):
                    selected_index = indexes[index_idx]
                    break
                else:
                    print(f"1から{len(indexes)}の範囲で選択してください。")
            except ValueError:
                print("数値を入力してください。")
        
        # スキーマの取得
        schema = get_index_schema(selected_index, credential)
        
        # 検索の実行
        search_results = search_documents(
            args.query, 
            selected_index, 
            schema, 
            credential, 
            args.top, 
            args.vector_exclude, 
            args.vector_type
        )
        
        # 検索結果の表示
        print(f"\n検索クエリ: {args.query}")
        print(f"検索結果: {search_results['count']} 件\n")
        
        # ドキュメントの表示
        display_documents(search_results["documents"], schema, args.verbose, args.summary_length)
        
        # ドキュメントがある場合、かつsearch_onlyでない場合は回答を生成
        if search_results["documents"] and not args.search_only:
            print("=== 生成された回答 ===")
            answer = generate_answer(
                args.query, 
                search_results["documents"], 
                schema, 
                args.max_context_length, 
                args.temperature, 
                args.max_tokens
            )
            print(answer)
        elif not search_results["documents"]:
            print("関連するドキュメントが見つかりませんでした。")

if __name__ == "__main__":
    main() 