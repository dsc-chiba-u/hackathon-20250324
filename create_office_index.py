#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Office文書（Word、Excel、PowerPoint）用のAzure AI Searchインデックスを作成するスクリプト
Blobストレージに格納されたOffice文書からインデックスを作成します
"""

import os
import argparse
import json
import requests
import time
import logging
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# API バージョン
API_VERSION = "2024-11-01-Preview"
DEFAULT_OFFICE_INDEX_NAME = "office-docs-index"
DEFAULT_CONTAINER_NAME = "documents"

# ロガーの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_search_headers():
    """検索APIリクエスト用のヘッダーを取得"""
    api_key = os.environ["AZURE_SEARCH_ADMIN_KEY"]
    return {
        "Content-Type": "application/json",
        "api-key": api_key
    }

def create_arg_parser():
    """コマンドライン引数のパーサーを作成"""
    parser = argparse.ArgumentParser(description="Office文書からインデックスを作成")
    parser.add_argument("--index-name", default=DEFAULT_OFFICE_INDEX_NAME, help=f"作成するインデックス名（デフォルト: {DEFAULT_OFFICE_INDEX_NAME}）")
    parser.add_argument("--container", default=DEFAULT_CONTAINER_NAME, help=f"検索対象のコンテナ名（デフォルト: {DEFAULT_CONTAINER_NAME}）")
    parser.add_argument("--prefix", default="contents/office", help="Blobプレフィックス（Office文書の格納場所、デフォルト: contents/office）")
    parser.add_argument("--use-skillset", action="store_true", help="Cognitive Servicesのスキルセットを使用する")
    parser.add_argument("--delete-only", action="store_true", help="リソースを削除するだけ")
    parser.add_argument("--debug", action="store_true", help="デバッグログを出力")
    return parser

def delete_search_resources(endpoint, index_name):
    """検索リソース（インデックス、インデクサー、スキルセット、データソース）を削除"""
    headers = get_search_headers()
    
    # インデックスを削除
    try:
        response = requests.delete(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
            headers=headers
        )
        if response.status_code == 204 or response.status_code == 404:
            logger.info(f"🗑️  インデックス '{index_name}' を削除しました")
        else:
            logger.warning(f"⚠️  インデックス '{index_name}' の削除に失敗: {response.text}")
    except Exception as e:
        logger.error(f"⚠️ インデックス削除エラー: {str(e)}")

    # インデクサーを削除
    indexer_name = f"{index_name}-indexer"
    try:
        response = requests.delete(
            f"{endpoint}/indexers/{indexer_name}?api-version={API_VERSION}",
            headers=headers
        )
        if response.status_code == 204 or response.status_code == 404:
            logger.info(f"🗑️  インデクサー '{indexer_name}' を削除しました")
        else:
            logger.warning(f"⚠️  インデクサー '{indexer_name}' の削除に失敗: {response.text}")
    except Exception as e:
        logger.error(f"⚠️ インデクサー削除エラー: {str(e)}")

    # スキルセットを削除
    skillset_name = f"{index_name}-skillset"
    try:
        response = requests.delete(
            f"{endpoint}/skillsets/{skillset_name}?api-version={API_VERSION}",
            headers=headers
        )
        if response.status_code == 204 or response.status_code == 404:
            logger.info(f"🗑️  スキルセット '{skillset_name}' を削除しました")
        else:
            logger.warning(f"⚠️  スキルセット '{skillset_name}' の削除に失敗: {response.text}")
    except Exception as e:
        logger.error(f"⚠️ スキルセット削除エラー: {str(e)}")

    # データソースを削除
    datasource_name = f"{index_name}-datasource"
    try:
        response = requests.delete(
            f"{endpoint}/datasources/{datasource_name}?api-version={API_VERSION}",
            headers=headers
        )
        if response.status_code == 204 or response.status_code == 404:
            logger.info(f"🗑️  データソース '{datasource_name}' を削除しました")
    else:
            logger.warning(f"⚠️  データソース '{datasource_name}' の削除に失敗: {response.text}")
    except Exception as e:
        logger.error(f"⚠️ データソース削除エラー: {str(e)}")

def create_office_index(endpoint, index_name):
    """Office文書用のインデックスを作成"""
    headers = get_search_headers()
    
    # Office文書用のインデックス定義
    index_definition = {
        "name": index_name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "searchable": False},
            {"name": "content", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "merged_content", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "metadata_storage_name", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "metadata_storage_path", "type": "Edm.String", "searchable": False, "filterable": True, "sortable": True},
            {"name": "metadata_storage_size", "type": "Edm.Int64", "searchable": False, "filterable": True, "sortable": True},
            {"name": "metadata_content_type", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "metadata_author", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "metadata_last_modified", "type": "Edm.DateTimeOffset", "searchable": False, "filterable": True, "sortable": True},
            {"name": "metadata_creation_date", "type": "Edm.DateTimeOffset", "searchable": False, "filterable": True, "sortable": True},
            {"name": "metadata_title", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "language", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            # 明示的に大きなテキストフィールドのfacetable属性をfalseに設定
            {"name": "translated_text", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            # 言語ごとの翻訳フィールドを追加
            {"name": "translated_text_ja", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "translated_text_en", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "translated_text_fr", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "translated_text_es", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "translated_text_de", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "translated_text_zh_Hans", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False, "facetable": False},
            {"name": "keyphrases", "type": "Collection(Edm.String)", "searchable": True, "filterable": True, "facetable": True}
            # ベクトル検索は一時的に無効化
        ]
    }
    
    # インデックスを作成
    try:
    response = requests.put(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
        headers=headers,
        json=index_definition
    )
        if response.status_code == 201 or response.status_code == 200:
        logger.info(f"✅ インデックス '{index_name}' を作成しました")
        return True
    else:
            logger.error(f"⚠️  インデックス '{index_name}' の作成に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ インデックス作成エラー: {str(e)}")
        return False

def create_skillset(endpoint, index_name, cognitive_services_key, cognitive_services_endpoint):
    """Office文書処理用のスキルセットを作成"""
    headers = get_search_headers()
    
    skillset_name = f"{index_name}-skillset"

    # Office文書処理用のスキルセット定義
    skillset_definition = {
        "name": skillset_name,
        "description": "Office文書処理用のスキルセット",
        "cognitiveServices": {
            "@odata.type": "#Microsoft.Azure.Search.CognitiveServicesByKey",
            "description": "Cognitive Servicesキーによる統合",
            "key": cognitive_services_key
        },
        "skills": [
            # テキスト分割スキル - 大きなドキュメントを処理可能なサイズのチャンクに分割
            {
                "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
                "context": "/document",
                "textSplitMode": "pages",
                "maximumPageLength": 1000,        # チャンクサイズを小さくして処理を最適化
                "pageOverlapLength": 100,         # オーバーラップも適切に調整
                "defaultLanguageCode": "ja",      # デフォルト言語を設定
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/content"
                    }
                ],
                "outputs": [
                    {
                        "name": "textItems",
                        "targetName": "pages"
                    }
                ]
            },
            # テキストの統合 - 分割されたページを再結合
            {
                "@odata.type": "#Microsoft.Skills.Text.MergeSkill",
                "context": "/document",
                "insertPreTag": " ",
                "insertPostTag": " ",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/content"
                    },
                    {
                        "name": "itemsToInsert",
                        "source": "/document/pages/*"
                    }
                ],
                "outputs": [
                    {
                        "name": "mergedText",
                        "targetName": "merged_content"
                    }
                ]
            },
            # 言語検出スキル - ページごとに適用
            {
                "@odata.type": "#Microsoft.Skills.Text.LanguageDetectionSkill",
                "context": "/document/pages/*",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/pages/*"
                    }
                ],
                "outputs": [
                    {
                        "name": "languageCode",
                        "targetName": "language"
                    }
                ]
            },
            # ドキュメント全体の言語を最初のページの言語から決定
            {
                "@odata.type": "#Microsoft.Skills.Util.ShaperSkill",
                "context": "/document",
                "inputs": [
                    {
                        "name": "language",
                        "source": "/document/pages/0/language"
                    }
                ],
                "outputs": [
                    {
                        "name": "output",
                        "targetName": "language"
                    }
                ]
            },
            # キーフレーズ抽出スキル - ページごとに適用
            {
                "@odata.type": "#Microsoft.Skills.Text.KeyPhraseExtractionSkill",
                "context": "/document/pages/*",
                "defaultLanguageCode": "ja",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/pages/*"
                    }
                ],
                "outputs": [
                    {
                        "name": "keyPhrases",
                        "targetName": "keyPhrasesForPage"
                    }
                ]
            }
            # 翻訳スキルは一時的に無効化
        ]
    }
    
    # スキルセットを作成
    try:
    response = requests.put(
            f"{endpoint}/skillsets/{skillset_name}?api-version={API_VERSION}",
        headers=headers,
        json=skillset_definition
    )
        if response.status_code == 201 or response.status_code == 200:
        logger.info(f"✅ スキルセット '{skillset_name}' を作成しました")
        return True
    else:
            logger.error(f"⚠️  スキルセット '{skillset_name}' の作成に失敗: {response.text}")
            logger.error(response.text)
            return False
    except Exception as e:
        logger.error(f"⚠️ スキルセット作成エラー: {str(e)}")
        return False

def create_datasource(endpoint, index_name, container_name, connection_string, prefix):
    """Blobストレージのデータソースを作成"""
    headers = get_search_headers()

    datasource_name = f"{index_name}-datasource"

    # データソース定義
    datasource_definition = {
        "name": datasource_name,
        "type": "azureblob",
        "credentials": {
            "connectionString": connection_string
        },
        "container": {
            "name": container_name,
            "query": prefix
        }
    }

    # データソースを作成
    try:
        response = requests.put(
            f"{endpoint}/datasources/{datasource_name}?api-version={API_VERSION}",
            headers=headers,
            json=datasource_definition
        )
        if response.status_code == 201 or response.status_code == 200:
            logger.info(f"✅ データソース '{datasource_name}' を作成しました")
            return True
        else:
            logger.error(f"⚠️  データソース '{datasource_name}' の作成に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ データソース作成エラー: {str(e)}")
        return False

def create_indexer(endpoint, index_name, use_skillset=False):
    """Office文書処理用のインデクサーを作成"""
    headers = get_search_headers()

    indexer_name = f"{index_name}-indexer"
    datasource_name = f"{index_name}-datasource"
    skillset_name = f"{index_name}-skillset"
    
    # インデクサー定義
    indexer_definition = {
        "name": indexer_name,
        "description": "Office文書処理用のインデクサー",
        "dataSourceName": datasource_name,
        "targetIndexName": index_name,
        "parameters": {
            "batchSize": 1,  # 大きなファイルを処理するため小さいバッチサイズを使用
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
            },
            {
                "sourceFieldName": "metadata_storage_name",
                "targetFieldName": "metadata_storage_name"
            },
            {
                "sourceFieldName": "metadata_content_type",
                "targetFieldName": "metadata_content_type"
            },
            {
                "sourceFieldName": "metadata_last_modified",
                "targetFieldName": "metadata_last_modified"
            },
            {
                "sourceFieldName": "metadata_author",
                "targetFieldName": "metadata_author"
            },
            {
                "sourceFieldName": "metadata_title",
                "targetFieldName": "metadata_title"
            },
            {
                "sourceFieldName": "metadata_creation_date",
                "targetFieldName": "metadata_creation_date"
            }
        ]
    }

    # スキルセットを使用する場合は、インデクサー定義に追加
    if use_skillset:
        indexer_definition["skillsetName"] = skillset_name
        indexer_definition["outputFieldMappings"] = [
            {
                "sourceFieldName": "/document/merged_content",
                "targetFieldName": "content"
            },
            {
                "sourceFieldName": "/document/merged_content",
                "targetFieldName": "merged_content"
            },
            {
                "sourceFieldName": "/document/language",
                "targetFieldName": "language"
            },
            {
                "sourceFieldName": "/document/pages/*/keyPhrasesForPage/*",
                "targetFieldName": "keyphrases"
            }
        ]
    
    # インデクサーを作成
    try:
    response = requests.put(
            f"{endpoint}/indexers/{indexer_name}?api-version={API_VERSION}",
        headers=headers,
        json=indexer_definition
    )
        if response.status_code == 201 or response.status_code == 200:
        logger.info(f"✅ インデクサー '{indexer_name}' を作成しました")
        return True
    else:
            logger.error(f"⚠️  インデクサー '{indexer_name}' の作成に失敗: {response.text}")
            logger.error(response.text)
            return False
    except Exception as e:
        logger.error(f"⚠️ インデクサー作成エラー: {str(e)}")
        return False

def run_indexer(endpoint, index_name):
    """インデクサーを実行"""
    headers = get_search_headers()
    
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
            logger.warning(f"⚠️  インデクサー '{indexer_name}' の実行に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ インデクサー実行エラー: {str(e)}")
        return False

def update_semantic_configuration(endpoint, index_name):
    """インデックスのセマンティック設定を詳細に調整"""
    headers = get_search_headers()
    
    # APIバージョンに合わせたセマンティック設定
    semantic_config = {
        "semantic": {
            "configurations": [
                {
                    "name": "office-semantic-config",
                    "prioritizedFields": {
                        "titleField": {
                            "fieldName": "metadata_title"
                        },
                        "prioritizedContentFields": [
                            {
                                "fieldName": "content"
                            },
                            {
                                "fieldName": "translated_text_ja"
                            },
                            {
                                "fieldName": "translated_text_en"
                            }
                        ],
                        "prioritizedKeywordsFields": [
                            {
                                "fieldName": "keyphrases"
                            }
                        ]
                    }
                }
            ]
        }
    }
    
    # インデックスのセマンティック設定を更新
    try:
        # まずインデックスの最新情報を取得
        get_response = requests.get(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
            headers=headers
        )
        
        if get_response.status_code != 200:
            logger.error(f"⚠️  インデックス情報の取得に失敗: {get_response.text}")
            return False
            
        # 現在のインデックス定義を取得
        index_info = get_response.json()
        
        # セマンティック設定を追加または更新
        index_info["semantic"] = semantic_config["semantic"]
        
        # 更新されたインデックス定義を送信
        response = requests.put(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
            headers=headers,
            json=index_info
        )
        
        if response.status_code == 200 or response.status_code == 201:
            logger.info(f"✅ セマンティック設定を '{index_name}' に適用しました")
            return True
        else:
            logger.error(f"⚠️  セマンティック設定の適用に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ セマンティック設定エラー: {str(e)}")
        return False

def create_semantic_ranking_profile(endpoint, index_name):
    """セマンティックランキングプロファイルを作成/更新"""
    headers = get_search_headers()
    
    # インデックス情報を取得
    try:
        response = requests.get(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
            headers=headers
        )
        
        if response.status_code != 200:
            logger.error(f"⚠️  インデックス情報の取得に失敗: {response.text}")
            return False
            
        index_info = response.json()
        scoring_profiles = index_info.get("scoringProfiles", [])
        
        # ハイブリッドスコアリングプロファイルを追加
        hybrid_profile = {
            "name": "vector-hybrid-profile",
            "text": {
                "weights": {
                    "metadata_title": 5,
                    "keyphrases": 3,
                    "content": 2,
                    "translated_text_ja": 2,
                    "translated_text_en": 1
                }
            },
            "functions": [
                {
                    "type": "magnitude",
                    "boost": 2,
                    "fieldName": "keyphrases",
                    "interpolation": "constant"
                }
            ]
        }
        
        # 既存のプロファイルに存在しない場合のみ追加
        profile_exists = False
        for profile in scoring_profiles:
            if profile.get("name") == "vector-hybrid-profile":
                profile_exists = True
                break
                
        if not profile_exists:
            scoring_profiles.append(hybrid_profile)
            index_info["scoringProfiles"] = scoring_profiles
        
        # スコアリングプロファイルを更新した状態でインデックスを更新
        response = requests.put(
            f"{endpoint}/indexes/{index_name}?api-version={API_VERSION}",
            headers=headers,
            json=index_info
        )
        
        if response.status_code == 200 or response.status_code == 201:
            logger.info(f"✅ スコアリングプロファイル 'vector-hybrid-profile' を '{index_name}' に適用しました")
            return True
        else:
            logger.error(f"⚠️  スコアリングプロファイルの適用に失敗: {response.text}")
        return False
    
    except Exception as e:
        logger.error(f"⚠️ スコアリングプロファイル作成エラー: {str(e)}")
        return False

def main():
    """メイン関数"""
    # コマンドライン引数を解析
    parser = create_arg_parser()
    args = parser.parse_args()

    # ロギングレベルを設定
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Azure Search サービスのエンドポイントを取得
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    if not search_endpoint:
        logger.error("⚠️ 環境変数 'AZURE_SEARCH_ENDPOINT' が設定されていません")
        return

    # ベースとなるコンテナ名を設定
    container_name = args.container

    # ストレージ接続文字列を取得
    storage_connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if not storage_connection_string:
        logger.error("⚠️ 環境変数 'AZURE_STORAGE_CONNECTION_STRING' が設定されていません")
        return

    # Cognitive Services のキーとエンドポイントを取得
    cognitive_services_key = os.environ.get("AZURE_COGNITIVE_SERVICES_KEY", "")
    cognitive_services_endpoint = os.environ.get("AZURE_COGNITIVE_SERVICES_ENDPOINT", "")
    if args.use_skillset and (not cognitive_services_key or not cognitive_services_endpoint):
        logger.error("⚠️ Cognitive Servicesの設定が不足しています")
        return

    # リソースを削除
    delete_search_resources(search_endpoint, args.index_name)
    
    # 削除のみの場合はここで終了
    if args.delete_only:
        return
        
    # リソースを作成
    if create_office_index(search_endpoint, args.index_name):
        logger.info(f"🔍 インデックス '{args.index_name}' を作成しました")
    else:
        logger.error(f"⚠️ インデックス '{args.index_name}' の作成に失敗しました")
        return

    # スキルセットの作成（必要な場合）
    if args.use_skillset:
        if create_skillset(search_endpoint, args.index_name, cognitive_services_key, cognitive_services_endpoint):
            logger.info(f"🧠 スキルセット '{args.index_name}-skillset' を作成しました")
        else:
            logger.error(f"⚠️ スキルセット '{args.index_name}-skillset' の作成に失敗しました")
            return

    # データソースの作成
    if create_datasource(search_endpoint, args.index_name, container_name, storage_connection_string, args.prefix):
        logger.info(f"📂 データソース '{args.index_name}-datasource' を作成しました")
    else:
        logger.error(f"⚠️ データソース '{args.index_name}-datasource' の作成に失敗しました")
        return

    # インデクサーの作成
    if create_indexer(search_endpoint, args.index_name, args.use_skillset):
        logger.info(f"🔄 インデクサー '{args.index_name}-indexer' を作成しました")
    else:
        logger.error(f"⚠️ インデクサー '{args.index_name}-indexer' の作成に失敗しました")
        return
        
    # セマンティック設定の更新
    if update_semantic_configuration(search_endpoint, args.index_name):
        logger.info(f"🧠 セマンティック設定を '{args.index_name}' に適用しました")
    else:
        logger.warning(f"⚠️ セマンティック設定の適用に問題がありました")
        
    # セマンティックランキングプロファイルの作成
    if create_semantic_ranking_profile(search_endpoint, args.index_name):
        logger.info(f"⚖️ スコアリングプロファイルを '{args.index_name}' に適用しました")
    else:
        logger.warning(f"⚠️ スコアリングプロファイルの適用に問題がありました")

    logger.info(f"✅ インデックス作成が完了しました。インデックス名: {args.index_name}")
    logger.info(f"🔍 インデクサーの状態を確認するには以下のコマンドを実行してください:")
    logger.info(f"   python index_manager.py --action check --index-name {args.index_name}")

if __name__ == "__main__":
    exit(main()) 