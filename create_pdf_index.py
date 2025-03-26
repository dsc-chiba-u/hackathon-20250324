#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PDFファイル用のAzure AI Searchインデックスを作成するスクリプト - 最適化版
Blobストレージに格納されたPDFファイルからインデックスを作成します
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
DEFAULT_PDF_INDEX_NAME = "pdf-docs-index"
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
    parser = argparse.ArgumentParser(description="PDFファイルからインデックスを作成")
    parser.add_argument("--index-name", default=DEFAULT_PDF_INDEX_NAME, help=f"作成するインデックス名（デフォルト: {DEFAULT_PDF_INDEX_NAME}）")
    parser.add_argument("--container", default=DEFAULT_CONTAINER_NAME, help=f"検索対象のコンテナ名（デフォルト: {DEFAULT_CONTAINER_NAME}）")
    parser.add_argument("--prefix", default="contents/pdf", help="Blobプレフィックス（PDFファイルの格納場所、デフォルト: contents/pdf）")
    parser.add_argument("--use-skillset", action="store_true", help="Cognitive Servicesのスキルセットを使用する")
    parser.add_argument("--delete-only", action="store_true", help="リソースを削除するだけ")
    parser.add_argument("--debug", action="store_true", help="デバッグログを出力")
    parser.add_argument("--vector-search", action="store_true", help="ベクトル検索を有効にする")
    parser.add_argument("--env-file", default="environment/hackathon20250324.env", help="環境変数ファイルのパス（デフォルト: environment/hackathon20250324.env）")
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

def create_pdf_index(endpoint, index_name, use_vector=False):
    """PDFファイル用のインデックスを作成"""
    headers = get_search_headers()

    # PDFファイル用のインデックス定義
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
            {"name": "language", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
            {"name": "translated_text", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "keyphrases", "type": "Collection(Edm.String)", "searchable": True, "filterable": True, "facetable": True},
            {"name": "translated_text_ja", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "translated_text_en", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "translated_text_fr", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "translated_text_es", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "translated_text_de", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
            {"name": "translated_text_zh_Hans", "type": "Edm.String", "searchable": True, "filterable": False, "sortable": False},
        ]
    }

    # ベクトル検索フィールドを追加
    if use_vector:
        vector_field = {
            "name": "vector",
            "type": "Collection(Edm.Single)",
            "searchable": True,
            "filterable": False,
            "sortable": False,
            "facetable": False,
            "dimensions": 1536,  # OpenAI の埋め込みモデルの次元数
            "vectorSearchProfile": "my-vector-config"
        }
        index_definition["fields"].append(vector_field)
        
        # ベクトル検索プロファイルを追加 (2024-11-01-Preview API向けに修正)
        index_definition["vectorSearch"] = {
            "profiles": [
                {
                    "name": "my-vector-config",
                    "algorithm": "hnsw"  # algorithmConfiguration から algorithm に変更
                }
            ],
            "algorithms": [
                {
                    "name": "hnsw",
                    "kind": "hnsw"
                }
            ]
        }

    # セマンティック検索設定を追加
    # 注：現在のAPIバージョンでの互換性の問題のため、一時的に無効化
    # semantic_config_name = os.environ.get("AZURE_SEARCH_SEMANTIC_CONFIG", "")
    # if semantic_config_name:
    #     # 言語を日本語に設定
    #     index_definition["semantic"] = {
    #         "configurations": [
    #             {
    #                 "name": semantic_config_name,
    #                 "prioritizedFields": {
    #                     "titleField": "metadata_storage_name",
    #                     "prioritizedContentFields": ["content"],
    #                     "prioritizedKeywordsFields": ["keyphrases"]
    #                 }
    #             }
    #         ]
    #     }

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
    """PDF処理用のスキルセットを作成"""
    headers = get_search_headers()

    skillset_name = f"{index_name}-skillset"

    # PDF処理用のスキルセット定義
    skillset_definition = {
        "name": skillset_name,
        "description": "PDF document processing skillset",
        "skills": [
            # PDFからテキストを抽出するスキル
            {
                "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
                "textSplitMode": "pages",
                "maximumPageLength": 5000,
                "defaultLanguageCode": "ja",
                "context": "/document",
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
            # テキストをマージするスキル
            {
                "@odata.type": "#Microsoft.Skills.Text.MergeSkill",
                "insertPreTag": " ",
                "insertPostTag": " ",
                "context": "/document",
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
            # 言語検出スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.LanguageDetectionSkill",
                "context": "/document",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "languageCode",
                        "targetName": "language"
                    }
                ]
            },
            # キーフレーズ抽出スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.KeyPhraseExtractionSkill",
                "context": "/document",
                "defaultLanguageCode": "ja",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    },
                    {
                        "name": "languageCode",
                        "source": "/document/language"
                    }
                ],
                "outputs": [
                    {
                        "name": "keyPhrases",
                        "targetName": "keyphrases"
                    }
                ]
            },
            # 日本語から英語への翻訳スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.TranslationSkill",
                "context": "/document",
                "defaultToLanguageCode": "en",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "translatedText",
                        "targetName": "translated_text_en"
                    }
                ]
            },
            # 英語から日本語への翻訳スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.TranslationSkill",
                "context": "/document",
                "defaultFromLanguageCode": "en",
                "defaultToLanguageCode": "ja",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "translatedText",
                        "targetName": "translated_text_ja"
                    }
                ]
            },
            # 英語からフランス語への翻訳スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.TranslationSkill",
                "context": "/document",
                "defaultFromLanguageCode": "en",
                "defaultToLanguageCode": "fr",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "translatedText",
                        "targetName": "translated_text_fr"
                    }
                ]
            },
            # 英語からスペイン語への翻訳スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.TranslationSkill",
                "context": "/document",
                "defaultFromLanguageCode": "en",
                "defaultToLanguageCode": "es",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "translatedText",
                        "targetName": "translated_text_es"
                    }
                ]
            },
            # 英語からドイツ語への翻訳スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.TranslationSkill",
                "context": "/document",
                "defaultFromLanguageCode": "en",
                "defaultToLanguageCode": "de",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "translatedText",
                        "targetName": "translated_text_de"
                    }
                ]
            },
            # 英語から中国語簡体字への翻訳スキル
            {
                "@odata.type": "#Microsoft.Skills.Text.TranslationSkill",
                "context": "/document",
                "defaultFromLanguageCode": "en",
                "defaultToLanguageCode": "zh-Hans",
                "inputs": [
                    {
                        "name": "text",
                        "source": "/document/merged_content"
                    }
                ],
                "outputs": [
                    {
                        "name": "translatedText",
                        "targetName": "translated_text_zh_Hans"
                    }
                ]
            }
        ],
        "cognitiveServices": {
            "@odata.type": "#Microsoft.Azure.Search.CognitiveServicesByKey",
            "description": "Cognitive Services",
            "key": cognitive_services_key
        }
    }

    # ベクトル埋め込みを生成するカスタムスキル
    # 注：現在のAPIバージョンでの互換性の問題のため、一時的に無効化
    # openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    # openai_api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    # embedding_deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    
    # if openai_endpoint and openai_api_key and embedding_deployment:
    #     # ベクトル埋め込み用のカスタムWebスキル
    #     vector_skill = {
    #         "@odata.type": "#Microsoft.Skills.Custom.WebApiSkill",
    #         "name": "text-embedding-skill",
    #         "description": "Generate vector embeddings for text using Azure OpenAI",
    #         "uri": "https://aoai-vector-skill.azurewebsites.net/api/vectorize",
    #         "httpMethod": "POST",
    #         "timeout": "PT2M",
    #         "context": "/document",
    #         "batchSize": 1,
    #         "inputs": [
    #             {
    #                 "name": "text",
    #                 "source": "/document/merged_content"
    #             },
    #             {
    #                 "name": "openai_endpoint",
    #                 "source": "_openai_endpoint"
    #             },
    #             {
    #                 "name": "openai_api_key",
    #                 "source": "_openai_api_key"
    #             },
    #             {
    #                 "name": "openai_deployment",
    #                 "source": "_openai_deployment"
    #             }
    #         ],
    #         "outputs": [
    #             {
    #                 "name": "vector",
    #                 "targetName": "vector"
    #             }
    #         ],
    #         "httpHeaders": {}
    #     }
        
    #     # スキルセットにベクトル埋め込みスキルを追加
    #     skillset_definition["skills"].append(vector_skill)
        
    #     # 環境変数を設定 - 最新のAPIではinlineプロパティが使用できない
    #     # inline の代わりに parameters を使用
    #     skillset_definition["knowledgeStore"] = {
    #         "projections": []
    #     }
    #     skillset_definition["parameters"] = {
    #         "_openai_endpoint": openai_endpoint,
    #         "_openai_api_key": openai_api_key,
    #         "_openai_deployment": embedding_deployment
    #     }

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
            return False
    except Exception as e:
        logger.error(f"⚠️ スキルセット作成エラー: {str(e)}")
        return False

def create_datasource(endpoint, index_name, container_name, connection_string, prefix):
    """Blobデータソースを作成"""
    headers = get_search_headers()

    datasource_name = f"{index_name}-datasource"

    # 特定のプレフィックスのPDFファイルのみを対象とする
    query = prefix  # f"{prefix}/*.pdf" から変更

    # データソース定義
    datasource_definition = {
        "name": datasource_name,
        "description": "PDF documents in Azure Blob Storage",
        "type": "azureblob",
        "credentials": {
            "connectionString": connection_string
        },
        "container": {
            "name": container_name,
            "query": query
        },
        "dataDeletionDetectionPolicy": {
            "@odata.type": "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy",
            "softDeleteColumnName": "isDeleted",
            "softDeleteMarkerValue": "true"
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

def create_indexer(endpoint, index_name, use_skillset):
    """PDFインデクサーを作成"""
    headers = get_search_headers()

    indexer_name = f"{index_name}-indexer"
    datasource_name = f"{index_name}-datasource"
    skillset_name = f"{index_name}-skillset"

    # インデクサー定義
    indexer_definition = {
        "name": indexer_name,
        "description": "PDF document indexer",
        "dataSourceName": datasource_name,
        "targetIndexName": index_name,
        "parameters": {
            "configuration": {
                "dataToExtract": "contentAndMetadata",
                "parsingMode": "default",
                "indexStorageMetadataOnlyForOversizedDocuments": True,
                "indexedFileNameExtensions": ".pdf",
                "failOnUnsupportedContentType": False,
                "failOnUnprocessableDocument": False
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
                "sourceFieldName": "metadata_storage_path",
                "targetFieldName": "metadata_storage_path"
            },
            {
                "sourceFieldName": "metadata_storage_name",
                "targetFieldName": "metadata_storage_name"
            },
            {
                "sourceFieldName": "metadata_storage_size",
                "targetFieldName": "metadata_storage_size"
            },
            {
                "sourceFieldName": "metadata_content_type",
                "targetFieldName": "metadata_content_type"
            }
        ],
        "outputFieldMappings": []
    }

    # スキルセットが有効な場合はマッピングを追加
    if use_skillset:
        indexer_definition["skillsetName"] = skillset_name
        indexer_definition["outputFieldMappings"] = [
            {
                "sourceFieldName": "/document/language",
                "targetFieldName": "language"
            },
            {
                "sourceFieldName": "/document/merged_content",
                "targetFieldName": "content"
            },
            {
                "sourceFieldName": "/document/merged_content",
                "targetFieldName": "merged_content"
            },
            {
                "sourceFieldName": "/document/keyphrases",
                "targetFieldName": "keyphrases"
            },
            {
                "sourceFieldName": "/document/translated_text_ja",
                "targetFieldName": "translated_text_ja"
            },
            {
                "sourceFieldName": "/document/translated_text_en",
                "targetFieldName": "translated_text_en"
            },
            {
                "sourceFieldName": "/document/translated_text_fr",
                "targetFieldName": "translated_text_fr"
            },
            {
                "sourceFieldName": "/document/translated_text_es",
                "targetFieldName": "translated_text_es"
            },
            {
                "sourceFieldName": "/document/translated_text_de",
                "targetFieldName": "translated_text_de"
            },
            {
                "sourceFieldName": "/document/translated_text_zh_Hans",
                "targetFieldName": "translated_text_zh_Hans"
            }
        ]
        
        # ベクトル埋め込みマッピングも追加（スキルセットに含まれている場合）
        # 注：現在のAPIバージョンでの互換性の問題のため、一時的に無効化
        # vector_mapping = {
        #     "sourceFieldName": "/document/vector",
        #     "targetFieldName": "vector"
        # }
        # indexer_definition["outputFieldMappings"].append(vector_mapping)

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
            return False
    except Exception as e:
        logger.error(f"⚠️ インデクサー作成エラー: {str(e)}")
        return False

def run_indexer(endpoint, index_name):
    """PDFインデクサーを実行"""
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
            logger.error(f"⚠️  インデクサー '{indexer_name}' の実行に失敗: {response.text}")
            return False
    except Exception as e:
        logger.error(f"⚠️ インデクサー実行エラー: {str(e)}")
        return False

def main():
    """メイン関数"""
    # コマンドライン引数の解析
    parser = create_arg_parser()
    args = parser.parse_args()

    # デバッグモードが有効な場合はログレベルをDEBUGに設定
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("デバッグモードが有効です")

    # コマンドライン引数で指定された環境変数ファイルを読み込む
    if args.env_file:
        logger.info(f"環境変数ファイル '{args.env_file}' を読み込みます")
        load_dotenv(args.env_file)

    # Azure AI Search エンドポイントを取得
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    if not search_endpoint:
        logger.error("⚠️ 環境変数 'AZURE_SEARCH_ENDPOINT' が設定されていません")
        return False

    # インデックス名を取得
    index_name = args.index_name

    # 既存のリソースを削除
    delete_search_resources(search_endpoint, index_name)

    # 削除のみのモードの場合はここで終了
    if args.delete_only:
        logger.info("✅ リソースの削除が完了しました")
        return True

    # PDFインデックスを作成
    if not create_pdf_index(search_endpoint, index_name, args.vector_search):
        logger.error("⚠️ インデックスの作成に失敗しました")
        return False

    # スキルセットを使用する場合
    if args.use_skillset:
        # Cognitive Services の接続情報を取得
        # AIServices.S0タイプではなく、all-in-oneタイプのキーが必要
        cognitive_services_key = os.environ.get("AZURE_COGNITIVE_ALLINONE_KEY")
        cognitive_services_endpoint = os.environ.get("AZURE_COGNITIVE_ALLINONE_ENDPOINT")

        if not cognitive_services_key or not cognitive_services_endpoint:
            logger.error("⚠️ Cognitive Services の接続情報が設定されていません")
            return False

        # スキルセットを作成
        if not create_skillset(search_endpoint, index_name, cognitive_services_key, cognitive_services_endpoint):
            logger.error("⚠️ スキルセットの作成に失敗しました")
            return False

    # Blobストレージの接続情報を取得
    storage_connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not storage_connection_string:
        logger.error("⚠️ 環境変数 'AZURE_STORAGE_CONNECTION_STRING' が設定されていません")
        return False

    # データソースを作成
    if not create_datasource(search_endpoint, index_name, args.container, storage_connection_string, args.prefix):
        logger.error("⚠️ データソースの作成に失敗しました")
        return False

    # インデクサーを作成
    if not create_indexer(search_endpoint, index_name, args.use_skillset):
        logger.error("⚠️ インデクサーの作成に失敗しました")
        return False

    # インデクサーを実行
    if not run_indexer(search_endpoint, index_name):
        logger.error("⚠️ インデクサーの実行に失敗しました")
        return False

    logger.info(f"✅ インデックス '{index_name}' の作成が完了しました")
    logger.info("🔍 インデックスの作成状況は Azure Portal で確認できます")
    return True

if __name__ == "__main__":
    main() 