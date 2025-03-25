#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
シンプルなOffice文書用インデックス作成スクリプト
================================================

このスクリプトはAzure Blobストレージに格納されたOffice文書（Word、Excel、PowerPoint）から
最小限の機能でAzure AI Searchインデックスを作成します。

主な機能:
- Office文書からのテキスト抽出とインデックス化
- 基本的なメタデータ（ファイル名、作成日、作成者など）の取得
- 1つの単純なスキルセット（言語検出）のサンプル

使用方法:
```bash
python create_office_simple_index.py --index-name "my-simple-index" --container "documents"
```

必要な環境変数:
- AZURE_SEARCH_ENDPOINT: Azure AI Searchのエンドポイント
- AZURE_SEARCH_ADMIN_KEY: 管理者キー
- AZURE_STORAGE_CONNECTION_STRING: Blobストレージの接続文字列
- AZURE_COGNITIVE_SERVICES_KEY: Cognitive Servicesのキー（言語検出スキル用）
- AZURE_COGNITIVE_SERVICES_ENDPOINT: Cognitive Servicesのエンドポイント

参考ドキュメント:
- Azure AI Search概要: https://learn.microsoft.com/ja-jp/azure/search/search-what-is-azure-search
- Blobインデクサー: https://learn.microsoft.com/ja-jp/azure/search/search-howto-indexing-azure-blob-storage
- スキルセット: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-working-with-skillsets

スキルセット関連のドキュメント:
- スキルセット概要: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-concept-intro
- 言語検出スキル: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-skill-language-detection
- OCRスキル: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-skill-ocr
- エンティティ認識スキル: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-skill-entity-recognition
- キーフレーズ抽出スキル: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-skill-keyphrases
- カスタムスキルの作成: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-create-custom-skill-example
- スキルセットのデバッグ: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-debug-session

コマンドラインスクリプト: https://learn.microsoft.com/ja-jp/azure/search/search-import-data-python

テクニカルリファレンス:
- REST API: https://learn.microsoft.com/ja-jp/rest/api/searchservice/
- Python SDK: https://learn.microsoft.com/ja-jp/python/api/overview/azure/search-documents-readme
"""

import os
import argparse
import logging
import requests
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# 定数
API_VERSION = "2024-11-01-Preview"
DEFAULT_INDEX_NAME = "office-simple-index"
DEFAULT_CONTAINER_NAME = "documents"

# ロガーの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_headers():
    """
    Azure AI Search API用のヘッダーを取得
    
    Azure AI SearchのREST APIを呼び出す際に必要な認証ヘッダーを生成します。
    api-keyを使った認証方式を使用します。
    
    Returns:
        dict: Content-TypeとAPI keyを含むヘッダー辞書
        
    Raises:
        ValueError: 環境変数 AZURE_SEARCH_ADMIN_KEY が設定されていない場合
        
    参考: https://learn.microsoft.com/ja-jp/rest/api/searchservice/create-index
    """
    api_key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    if not api_key:
        raise ValueError("環境変数 'AZURE_SEARCH_ADMIN_KEY' が設定されていません")
    
    return {
        "Content-Type": "application/json",
        "api-key": api_key
    }

def parse_arguments():
    """
    コマンドライン引数をパース
    
    スクリプトの動作を制御するためのコマンドライン引数を定義し、解析します。
    argparseモジュールを使用して引数を定義し、パースします。
    
    主なオプション:
    --index-name: インデックス名の指定
    --container: Blobコンテナ名の指定
    --prefix: Blobプレフィックスのフィルタリング
    --delete-only: 削除処理のみを実行
    --use-skillset: 言語検出スキルセットを使用するかどうか
    
    Returns:
        argparse.Namespace: パースされたコマンドライン引数のオブジェクト
        
    参考: https://docs.python.org/ja/3/library/argparse.html
    """
    parser = argparse.ArgumentParser(description="シンプルなOffice文書インデックスを作成")
    parser.add_argument("--index-name", default=DEFAULT_INDEX_NAME,
                        help=f"作成するインデックス名（デフォルト: {DEFAULT_INDEX_NAME}）")
    parser.add_argument("--container", default=DEFAULT_CONTAINER_NAME,
                        help=f"検索対象のコンテナ名（デフォルト: {DEFAULT_CONTAINER_NAME}）")
    parser.add_argument("--prefix", default="",
                        help="Blobプレフィックス（指定したパス以下のみを対象にする）")
    parser.add_argument("--delete-only", action="store_true",
                        help="既存のリソースを削除するのみ")
    parser.add_argument("--use-skillset", action="store_true",
                        help="言語検出のスキルセットを使用する")
    return parser.parse_args()

def delete_resources(endpoint, index_name):
    """
    検索リソースを削除
    
    Azure AI Searchのインデックス、インデクサー、スキルセット、データソースなどの
    リソースを削除します。新しいリソースを作成する前にクリーンアップするために使用します。
    
    処理の流れ:
    1. 各リソースタイプとリソース名のリストを作成
    2. 各リソースに対してDELETEリクエストを送信
    3. 成功・失敗をログに記録
    
    Args:
        endpoint (str): Azure AI Searchのエンドポイント
        index_name (str): 削除するリソースの基本名
        
    参考:
    - https://learn.microsoft.com/ja-jp/rest/api/searchservice/delete-index
    - https://learn.microsoft.com/ja-jp/rest/api/searchservice/delete-indexer
    """
    headers = get_headers()
    resources = [
        ("indexes", index_name, "インデックス"),
        ("indexers", f"{index_name}-indexer", "インデクサー"),
        ("skillsets", f"{index_name}-skillset", "スキルセット"),
        ("datasources", f"{index_name}-datasource", "データソース")
    ]
    
    for resource_type, resource_name, display_name in resources:
        try:
            response = requests.delete(
                f"{endpoint}/{resource_type}/{resource_name}?api-version={API_VERSION}",
                headers=headers
            )
            if response.status_code in [204, 404]:
                logger.info(f"🗑️ {display_name} '{resource_name}' を削除しました")
            else:
                logger.warning(f"⚠️ {display_name} '{resource_name}' の削除に失敗: {response.text}")
        except Exception as e:
            logger.error(f"⚠️ {display_name}削除エラー: {str(e)}")

def create_index(endpoint, index_name):
    """
    シンプルなOffice文書用インデックスを作成
    
    Azure AI Searchのインデックスを作成します。インデックスはOffice文書の
    テキスト内容とメタデータを格納するためのスキーマを定義します。
    
    定義するフィールド:
    - id: ドキュメントの一意識別子（Blobパスをbase64エンコード）
    - content: ドキュメントから抽出されたテキスト内容
    - metadata_storage_name: ファイル名
    - metadata_storage_path: BlobのURI
    - metadata_content_type: MIMEタイプ
    - metadata_last_modified: 最終更新日
    - metadata_author: 作成者
    - metadata_title: タイトル
    - language: 検出された言語（スキルセット使用時）
    
    Args:
        endpoint (str): Azure AI Searchのエンドポイント
        index_name (str): 作成するインデックスの名前
        
    Returns:
        bool: インデックス作成の成功・失敗
        
    参考:
    - https://learn.microsoft.com/ja-jp/azure/search/search-what-is-an-index
    - https://learn.microsoft.com/ja-jp/rest/api/searchservice/create-index
    """
    headers = get_headers()
    
    # シンプルなインデックス定義
    index_definition = {
        "name": index_name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "searchable": False},
            {"name": "content", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "metadata_storage_name", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "metadata_storage_path", "type": "Edm.String", "searchable": False, "filterable": True, "sortable": False},
            {"name": "metadata_content_type", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "metadata_last_modified", "type": "Edm.DateTimeOffset", "searchable": False, "filterable": True, "sortable": True},
            {"name": "metadata_author", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "metadata_title", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "language", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True}
        ]
    }
    
    try:
        response = requests.put(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
            headers=headers,
            json=index_definition
        )
        if response.status_code in [200, 201]:
            logger.info(f"✅ インデックス '{index_name}' を作成しました")
            return True
        else:
            logger.error(f"⚠️ インデックス '{index_name}' の作成に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ インデックス作成エラー: {str(e)}")
        return False

def create_skillset(endpoint, index_name, cognitive_services_key):
    """
    シンプルな言語検出スキルセットを作成
    
    文書の言語を自動検出するためのシンプルなスキルセットを作成します。
    このスキルセットは、文書のコンテンツ（content）を入力として受け取り、
    検出した言語コード（ISO 639-1形式、例: "ja", "en"など）を出力します。
    
    スキルセットの動作:
    1. 文書のコンテンツを入力として受け取る
    2. Azure Cognitive Servicesの言語検出モデルで分析
    3. 検出された言語コードをlanguageフィールドに出力
    
    言語検出スキルでは、120以上の言語とその変種を検出できます。主要な言語コード:
    - 日本語: ja
    - 英語: en
    - 中国語（簡体字）: zh-Hans
    - 中国語（繁体字）: zh-Hant
    - フランス語: fr
    - ドイツ語: de
    - スペイン語: es
    - イタリア語: it
    - 韓国語: ko
    
    Args:
        endpoint (str): Azure AI Searchのエンドポイント
        index_name (str): 関連付けるインデックスの名前
        cognitive_services_key (str): Cognitive Servicesのキー
        
    Returns:
        bool: スキルセット作成の成功・失敗
        
    参考:
    - 言語検出スキル: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-skill-language-detection
    - スキルセットの定義: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-defining-skillset
    - 対応言語コード一覧: https://learn.microsoft.com/ja-jp/azure/ai-services/translator/language-support
    - スキルの入出力マッピング: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-concept-annotations-syntax
    - スキルセットの例: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-working-with-skillsets#example-skillset
    """
    headers = get_headers()
    
    skillset_name = f"{index_name}-skillset"

    # 言語検出のみのシンプルなスキルセット
    skillset_definition = {
        "name": skillset_name,
        "description": "言語検出のみの簡易スキルセット",
        "cognitiveServices": {
            "@odata.type": "#Microsoft.Azure.Search.CognitiveServicesByKey",
            "description": "Cognitive Services",
            "key": cognitive_services_key
        },
        "skills": [
            # 言語検出スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.LanguageDetectionSkill",
                "context": "/document",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/content"
                    }
                ],
                "outputs": [
                    {
                        "name": "languageCode",
                        "targetName": "language"
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.put(
            f"{endpoint}/skillsets/{skillset_name}?api-version={API_VERSION}",
            headers=headers,
            json=skillset_definition
        )
        if response.status_code in [200, 201]:
            logger.info(f"✅ スキルセット '{skillset_name}' を作成しました")
            return True
        else:
            logger.error(f"⚠️ スキルセット '{skillset_name}' の作成に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ スキルセット作成エラー: {str(e)}")
        return False

def create_datasource(endpoint, index_name, container_name, connection_string, prefix):
    """
    Blobストレージのデータソースを作成
    
    Azure Blobストレージをデータソースとして定義します。
    このデータソースはインデクサーがどのBlobコンテナから文書を取得するかを指定します。
    
    主な設定:
    - コンテナ名: 対象となるBlobコンテナ
    - プレフィックス: 特定のフォルダ（プレフィックス）に限定する場合に使用
    - 接続文字列: Blobストレージへの接続情報
    
    Args:
        endpoint (str): Azure AI Searchのエンドポイント
        index_name (str): 関連付けるインデックスの名前
        container_name (str): Blobコンテナ名
        connection_string (str): Blobストレージの接続文字列
        prefix (str): Blobプレフィックス（オプション）
        
    Returns:
        bool: データソース作成の成功・失敗
        
    参考:
    - https://learn.microsoft.com/ja-jp/azure/search/search-howto-indexing-azure-blob-storage
    - https://learn.microsoft.com/ja-jp/rest/api/searchservice/create-data-source
    """
    headers = get_headers()

    datasource_name = f"{index_name}-datasource"

    # シンプルなデータソース定義
    datasource_definition = {
        "name": datasource_name,
        "type": "azureblob",
        "credentials": {
            "connectionString": connection_string
        },
        "container": {
            "name": container_name
        }
    }
    
    # プレフィックスがある場合は追加
    if prefix:
        datasource_definition["container"]["query"] = prefix

    try:
        response = requests.put(
            f"{endpoint}/datasources/{datasource_name}?api-version={API_VERSION}",
            headers=headers,
            json=datasource_definition
        )
        if response.status_code in [200, 201]:
            logger.info(f"✅ データソース '{datasource_name}' を作成しました")
            return True
        else:
            logger.error(f"⚠️ データソース '{datasource_name}' の作成に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ データソース作成エラー: {str(e)}")
        return False

def create_indexer(endpoint, index_name, use_skillset):
    """
    インデクサーを作成
    
    Azure AI Searchのインデクサーを作成します。インデクサーは、データソースから
    ドキュメントを取得し、インデックスにデータを投入するプロセスを定義します。
    
    重要な設定:
    - dataToExtract: "contentAndMetadata" - テキスト内容とメタデータを抽出
    - parsingMode: "default" - 標準的な文書解析を使用
    - fieldMappings: データソースのフィールドをインデックスフィールドにマッピング
    - skillsetName: 使用するスキルセット（オプション）
    
    Args:
        endpoint (str): Azure AI Searchのエンドポイント
        index_name (str): ターゲットインデックスの名前
        use_skillset (bool): スキルセットを使用するかどうか
        
    Returns:
        bool: インデクサー作成の成功・失敗
        
    参考:
    - https://learn.microsoft.com/ja-jp/azure/search/search-indexer-overview
    - https://learn.microsoft.com/ja-jp/azure/search/search-howto-indexing-azure-blob-storage#indexing-documents
    - https://learn.microsoft.com/ja-jp/rest/api/searchservice/create-indexer
    """
    headers = get_headers()

    indexer_name = f"{index_name}-indexer"
    datasource_name = f"{index_name}-datasource"
    skillset_name = f"{index_name}-skillset"
    
    # インデクサー定義
    indexer_definition = {
        "name": indexer_name,
        "description": "Office文書の基本インデクサー",
        "dataSourceName": datasource_name,
        "targetIndexName": index_name,
        "parameters": {
            "configuration": {
                "dataToExtract": "contentAndMetadata",  # テキストとメタデータを抽出
                "parsingMode": "default"  # 標準の文書解析を使用
            }
        },
        "fieldMappings": [
            {
                "sourceFieldName": "metadata_storage_path",
                "targetFieldName": "id",
                "mappingFunction": {
                    "name": "base64Encode"  # パスをbase64エンコードしてIDとして使用
                }
            }
        ]
    }

    # スキルセットを使用する場合
    if use_skillset:
        indexer_definition["skillsetName"] = skillset_name
        indexer_definition["outputFieldMappings"] = [
            {
                "sourceFieldName": "/document/language",
                "targetFieldName": "language"
            }
        ]
    
    try:
        response = requests.put(
            f"{endpoint}/indexers/{indexer_name}?api-version={API_VERSION}",
            headers=headers,
            json=indexer_definition
        )
        if response.status_code in [200, 201]:
            logger.info(f"✅ インデクサー '{indexer_name}' を作成しました")
            return True
        else:
            logger.error(f"⚠️ インデクサー '{indexer_name}' の作成に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ インデクサー作成エラー: {str(e)}")
        return False

def run_indexer(endpoint, index_name):
    """
    インデクサーを実行
    
    作成したインデクサーを即時実行します。デフォルトではインデクサーは
    スケジュールに従って実行されますが、この関数では手動で即時実行を開始します。
    
    Args:
        endpoint (str): Azure AI Searchのエンドポイント
        index_name (str): 関連するインデックスの名前
        
    Returns:
        bool: インデクサー実行開始の成功・失敗
        
    参考:
    - https://learn.microsoft.com/ja-jp/rest/api/searchservice/run-indexer
    - https://learn.microsoft.com/ja-jp/azure/search/search-howto-run-reset-indexers
    """
    headers = get_headers()
    
    indexer_name = f"{index_name}-indexer"
    
    try:
        response = requests.post(
            f"{endpoint}/indexers/{indexer_name}/run?api-version={API_VERSION}",
            headers=headers
        )
        if response.status_code == 202:
            logger.info(f"✅ インデクサー '{indexer_name}' を実行しました")
            return True
        else:
            logger.warning(f"⚠️ インデクサー '{indexer_name}' の実行に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ インデクサー実行エラー: {str(e)}")
        return False

def main():
    """
    メイン処理 - Office文書インデックス作成プロセスの実行
    
    このスクリプトの主な実行フローを制御します。以下のステップで処理を行います:
    1. コマンドライン引数の解析
    2. 必要な環境変数の確認
    3. 既存リソースの削除
    4. インデックスの作成
    5. スキルセットの作成（オプション）
    6. データソースの作成
    7. インデクサーの作成
    8. インデクサーの実行開始
    
    スキルセットとCognitive Services:
    スキルセットを使用する場合（--use-skillset）は、Azure Cognitive Servicesのキーが
    必要になります。これは言語検出などのAI機能を使用するために必要です。
    スキルセットはインデクサーの実行プロセス中に適用され、抽出されたデータを
    強化します。例えば、言語検出スキルセットは文書の言語を自動的に特定し、
    languageフィールドに格納します。
    
    使用例:
    ```
    # 基本的な使用方法
    python create_office_simple_index.py --index-name "my-docs"
    
    # 言語検出スキルセットを使用
    python create_office_simple_index.py --use-skillset
    
    # 特定のフォルダ内のファイルのみインデックス化
    python create_office_simple_index.py --prefix "reports/2023"
    ```
    
    Returns:
        int: 処理結果のステータスコード (0:成功, 1:失敗)
    
    参考:
    - REST APIの使用: https://learn.microsoft.com/ja-jp/azure/search/search-get-started-rest
    - Blobインデックス作成: https://learn.microsoft.com/ja-jp/azure/search/search-howto-index-one-to-one-blobs
    - スキルセットとインデクサーの連携: https://learn.microsoft.com/ja-jp/azure/search/cognitive-search-tutorial-blob
    - インデクサーのスケジュール設定: https://learn.microsoft.com/ja-jp/azure/search/search-howto-schedule-indexers
    """
    # コマンドライン引数の解析
    args = parse_arguments()
    
    # 環境変数の取得
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    if not search_endpoint:
        logger.error("⚠️ 環境変数 'AZURE_SEARCH_ENDPOINT' が設定されていません")
        return 1
        
    storage_connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not storage_connection_string:
        logger.error("⚠️ 環境変数 'AZURE_STORAGE_CONNECTION_STRING' が設定されていません")
        return 1
    
    cognitive_services_key = os.environ.get("AZURE_COGNITIVE_SERVICES_KEY")
    if args.use_skillset and not cognitive_services_key:
        logger.error("⚠️ スキルセット使用時は環境変数 'AZURE_COGNITIVE_SERVICES_KEY' が必要です")
        return 1
    
    # 既存リソースの削除
    delete_resources(search_endpoint, args.index_name)
    
    # 削除のみの場合はここで終了
    if args.delete_only:
        return 0
    
    # インデックスの作成
    if not create_index(search_endpoint, args.index_name):
        return 1
    
    # スキルセットの作成（必要な場合）
    if args.use_skillset:
        if not create_skillset(search_endpoint, args.index_name, cognitive_services_key):
            return 1
    
    # データソースの作成
    if not create_datasource(search_endpoint, args.index_name, args.container, 
                             storage_connection_string, args.prefix):
        return 1
    
    # インデクサーの作成
    if not create_indexer(search_endpoint, args.index_name, args.use_skillset):
        return 1
    
    # インデクサーの実行
    run_indexer(search_endpoint, args.index_name)
    
    logger.info(f"✅ インデックス作成プロセスが完了しました。インデックス名: {args.index_name}")
    logger.info(f"📊 インデックスのステータスは Azure Portal で確認できます:")
    logger.info(f"   {search_endpoint.replace('https://', 'https://portal.azure.com/#@/resource')}indexes/{args.index_name}")
    return 0

if __name__ == "__main__":
    exit(main())
