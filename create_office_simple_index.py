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
- https://learn.microsoft.com/ja-jp/azure/search/search-howto-indexing-azure-blob-storage
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
    """Azure AI Search API用のヘッダーを取得"""
    api_key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    if not api_key:
        raise ValueError("環境変数 'AZURE_SEARCH_ADMIN_KEY' が設定されていません")
    
    return {
        "Content-Type": "application/json",
        "api-key": api_key
    }

def parse_arguments():
    """コマンドライン引数をパース"""
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
    """検索リソースを削除"""
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
    """シンプルなOffice文書用インデックスを作成"""
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
    """シンプルな言語検出スキルセットを作成"""
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
    """Blobストレージのデータソースを作成"""
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
    """インデクサーを作成"""
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
                "dataToExtract": "contentAndMetadata",
                "parsingMode": "default"
            }
        },
        "fieldMappings": [
            {
                "sourceFieldName": "metadata_storage_path",
                "targetFieldName": "id",
                "mappingFunction": {
                    "name": "base64Encode"
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
    """インデクサーを実行"""
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
    """メイン処理"""
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
    return 0

if __name__ == "__main__":
    exit(main())
