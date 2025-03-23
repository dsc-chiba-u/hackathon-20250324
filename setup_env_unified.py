#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import argparse
import subprocess
from typing import List, Dict, Optional
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.search import SearchManagementClient
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_args():
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(description='Azure リソースから環境変数を設定')
    parser.add_argument(
        '-g', '--resource-group',
        required=True,
        help='Azure リソースグループ名'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='出力する環境変数ファイルのパス'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='既存の出力ファイルを上書きする'
    )
    parser.add_argument(
        '--external-config',
        help='外部モデル設定ファイルのパス'
    )
    parser.add_argument(
        '--external-endpoint',
        help='外部エンベディングモデルのエンドポイント'
    )
    parser.add_argument(
        '--external-key',
        help='外部エンベディングモデルのAPIキー'
    )
    parser.add_argument(
        '--external-deployment',
        help='外部エンベディングモデルのデプロイメント名'
    )
    parser.add_argument(
        '--external-model',
        help='外部エンベディングモデルの名前'
    )
    parser.add_argument(
        '--external-api-version',
        default='2025-01-01-preview',
        help='外部エンベディングモデルのAPIバージョン'
    )
    
    # OpenAI特定のデプロイメント設定
    parser.add_argument(
        '--chat-model',
        help='使用するチャットモデル名（自動検出より優先）'
    )
    parser.add_argument(
        '--chat-deployment',
        help='使用するチャットモデルのデプロイメント名（自動検出より優先）'
    )
    parser.add_argument(
        '--embedding-model',
        help='使用するエンベディングモデル名（自動検出より優先）'
    )
    parser.add_argument(
        '--embedding-deployment',
        help='使用するエンベディングモデルのデプロイメント名（自動検出より優先）'
    )
    
    return parser.parse_args()

def load_external_config(config_path: str) -> Optional[Dict]:
    """外部設定ファイルを読み込む"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"外部設定ファイル '{config_path}' を読み込みました")
        return config
    except Exception as e:
        logger.error(f"外部設定ファイルの読み込みに失敗しました: {str(e)}")
        return None

def check_external_model(endpoint: str, api_key: str, deployment: str, api_version: str) -> bool:
    """外部モデルにアクセスできるか確認する"""
    try:
        # APIエンドポイントを構築
        full_endpoint = f"{endpoint}/openai/deployments/{deployment}/embeddings"
        
        # curl コマンドで簡易テスト
        test_command = (
            f'curl {full_endpoint}?api-version={api_version} '
            f'-H "Content-Type: application/json" '
            f'-H "api-key: {api_key}" '
            f'-d \'{{"input": "テストメッセージ"}}\' '
            f'-s | grep -q "embedding"'
        )
        
        # コマンドを実行
        subprocess.run(test_command, shell=True, check=True, 
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        logger.info(f"✅ 外部モデル '{deployment}' にアクセスできました")
        return True
    except Exception as e:
        logger.warning(f"外部モデルへのアクセスに失敗しました: {str(e)}")
        return False

def get_azure_clients(credential):
    """Azure クライアントを取得する"""
    subscription_id = os.getenv('AZURE_SUBSCRIPTION_ID')
    if not subscription_id:
        raise ValueError("AZURE_SUBSCRIPTION_ID environment variable is not set")
    
    return {
        'resource': ResourceManagementClient(credential, subscription_id),
        'storage': StorageManagementClient(credential, subscription_id),
        'search': SearchManagementClient(credential, subscription_id),
        'cognitive': CognitiveServicesManagementClient(credential, subscription_id)
    }

def get_storage_account(clients, resource_group: str):
    """ストレージアカウント情報を取得する"""
    storage_accounts = list(clients['storage'].storage_accounts.list_by_resource_group(resource_group))
    if not storage_accounts:
        return None
    
    account = storage_accounts[0]
    keys = clients['storage'].storage_accounts.list_keys(resource_group, account.name)
    return {
        'name': account.name,
        'key': keys.keys[0].value,
        'connection_string': f"DefaultEndpointsProtocol=https;AccountName={account.name};AccountKey={keys.keys[0].value};EndpointSuffix=core.windows.net"
    }

def get_search_service(clients, resource_group: str):
    """Cognitive Search サービス情報を取得する"""
    services = list(clients['search'].services.list_by_resource_group(resource_group))
    if not services:
        return None
    
    service = services[0]
    admin_keys = clients['search'].admin_keys.get(resource_group, service.name)
    return {
        'name': service.name,
        'endpoint': f"https://{service.name}.search.windows.net",
        'key': admin_keys.primary_key
    }

def get_openai_service(clients, resource_group):
    """OpenAIサービスの情報を取得する"""
    try:
        # 方法1: リソースグループ内の全Cognitive Servicesアカウントを検索
        accounts = list(clients['cognitive'].accounts.list_by_resource_group(resource_group))
        for account in accounts:
            account_name = account.name.lower()
            if account.kind == 'OpenAI' or 'openai' in account_name:
                logger.info(f"OpenAI サービス '{account.name}' がリソースグループ内で見つかりました")
                keys = clients['cognitive'].accounts.list_keys(resource_group, account.name)
                endpoint = f"https://{account.name}.cognitiveservices.azure.com/"
                
                # デプロイメント情報の取得
                deployments = get_openai_deployments(resource_group, account.name)
                
                # チャットとエンベディングモデルを識別
                chat_model, chat_deployment, embedding_model, embedding_deployment = identify_models(deployments)
                
                return create_openai_info(account.name, endpoint, keys.key1, 
                                         chat_model, chat_deployment, 
                                         embedding_model, embedding_deployment)
        
        # 方法2: リソースタイプでフィルタリングして検索
        resources = list(clients['resource'].resources.list_by_resource_group(
            resource_group_name=resource_group,
            filter="resourceType eq 'Microsoft.CognitiveServices/accounts'"
        ))
        
        for resource in resources:
            resource_name = resource.name.lower()
            if (hasattr(resource, 'kind') and resource.kind == 'OpenAI') or 'openai' in resource_name:
                logger.info(f"OpenAI サービス '{resource.name}' がリソースタイプで見つかりました")
                cognitive_client = clients['cognitive']
                keys = cognitive_client.accounts.list_keys(resource_group, resource.name)
                endpoint = f"https://{resource.name}.cognitiveservices.azure.com/"
                
                # デプロイメント情報の取得
                deployments = get_openai_deployments(resource_group, resource.name)
                
                # チャットとエンベディングモデルを識別
                chat_model, chat_deployment, embedding_model, embedding_deployment = identify_models(deployments)
                
                return create_openai_info(resource.name, endpoint, keys.key1, 
                                         chat_model, chat_deployment, 
                                         embedding_model, embedding_deployment)
        
        # OpenAIサービスが見つからなかった場合
        logger.warning(f"リソースグループ '{resource_group}' にOpenAIサービスが見つかりませんでした")
        # デフォルト値を設定して返す
        return {
            'AZURE_OPENAI_SERVICE': "NOT_FOUND",
            'AZURE_OPENAI_ENDPOINT': "NOT_FOUND",
            'AZURE_OPENAI_API_KEY': "NOT_FOUND",
            'AZURE_OPENAI_API_VERSION': '2025-01-01-preview',
            'CHAT_MODEL': "NOT_FOUND",
            'AZURE_OPENAI_CHAT_DEPLOYMENT': "NOT_FOUND",
            'EMBEDDING_MODEL': "NOT_FOUND",
            'AZURE_OPENAI_EMBEDDING_DEPLOYMENT': "NOT_FOUND"
        }
    except Exception as e:
        logger.error(f"OpenAIサービスの取得中にエラーが発生しました: {str(e)}")
        # エラー時もデフォルト値を返す
        return {
            'AZURE_OPENAI_SERVICE': "ERROR",
            'AZURE_OPENAI_ENDPOINT': "ERROR",
            'AZURE_OPENAI_API_KEY': "ERROR",
            'AZURE_OPENAI_API_VERSION': '2025-01-01-preview',
            'CHAT_MODEL': "ERROR",
            'AZURE_OPENAI_CHAT_DEPLOYMENT': "ERROR",
            'EMBEDDING_MODEL': "ERROR",
            'AZURE_OPENAI_EMBEDDING_DEPLOYMENT': "ERROR"
        }

def identify_models(deployments):
    """デプロイメントからチャットモデルとエンベディングモデルを識別する"""
    chat_model = None
    chat_deployment = None
    embedding_model = None
    embedding_deployment = None
    
    for deployment in deployments:
        model_name = deployment.get('model')
        deployment_name = deployment.get('name')
        
        if not model_name or not deployment_name:
            continue
            
        # GPTモデルはチャット用
        if 'gpt' in model_name.lower() or 'chat' in model_name.lower():
            # 最新のGPTモデルを優先（簡易的な実装）
            if not chat_model or 'gpt-4' in model_name.lower():
                chat_model = model_name
                chat_deployment = deployment_name
        
        # エンベディングモデル識別
        if 'embedding' in model_name.lower() or 'ada' in model_name.lower():
            embedding_model = model_name
            embedding_deployment = deployment_name
    
    return chat_model, chat_deployment, embedding_model, embedding_deployment

def create_openai_info(service_name, endpoint, api_key, chat_model, chat_deployment, embedding_model, embedding_deployment):
    """OpenAI情報を辞書形式で作成する"""
    return {
        'AZURE_OPENAI_SERVICE': service_name,
        'AZURE_OPENAI_ENDPOINT': endpoint,
        'AZURE_OPENAI_API_KEY': api_key,
        'AZURE_OPENAI_API_VERSION': '2025-01-01-preview',  # デフォルトバージョン
        'CHAT_MODEL': chat_model or "NOT_FOUND",
        'AZURE_OPENAI_CHAT_DEPLOYMENT': chat_deployment or "NOT_FOUND",
        'EMBEDDING_MODEL': embedding_model or "NOT_FOUND",
        'AZURE_OPENAI_EMBEDDING_DEPLOYMENT': embedding_deployment or "NOT_FOUND"
    }

def get_openai_deployments(resource_group, openai_name):
    """OpenAIサービスのデプロイメント情報を取得する"""
    try:
        # Azure CLIを使用してデプロイメント情報を取得（SDKだと少し複雑なため）
        cmd = f"az cognitiveservices account deployment list --name {openai_name} --resource-group {resource_group}"
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deployments = json.loads(result.stdout)
        
        deployment_info = []
        for deployment in deployments:
            deployment_info.append({
                'name': deployment.get('name'),
                'model': deployment.get('properties', {}).get('model', {}).get('name'),
                'version': deployment.get('properties', {}).get('model', {}).get('version')
            })
        
        return deployment_info
    except Exception as e:
        logger.error(f"OpenAIデプロイメント情報の取得中にエラーが発生しました: {str(e)}")
        return []

def get_cognitive_services_allinone(clients, resource_group_name: str) -> Dict[str, str]:
    """Cognitive Services (all-in-one) タイプのリソース情報を取得する

    Args:
        clients: Azure SDKのクライアント
        resource_group_name (str): リソースグループ名

    Returns:
        Dict[str, str]: Cognitive Services (all-in-one) リソースの情報
    """
    try:
        # リソースグループ内のCognitive Servicesアカウントを取得
        accounts = list(clients['cognitive'].accounts.list_by_resource_group(resource_group_name))
        
        # CognitiveServicesタイプのリソースを探す（OpenAIタイプを除く）
        allinone_services = [acc for acc in accounts if acc.kind == 'CognitiveServices' and acc.kind != 'OpenAI']
        
        if not allinone_services:
            logger.warning(f"リソースグループ '{resource_group_name}' に all-in-one タイプの Cognitive Services が見つかりませんでした")
            return {}
        
        # 複数ある場合は最初のリソースを使用
        service = allinone_services[0]
        logger.info(f"All-in-one Cognitive Services '{service.name}' が見つかりました。")
        
        # キー情報を取得
        keys = clients['cognitive'].accounts.list_keys(resource_group_name, service.name)
        
        return {
            'name': service.name,
            'endpoint': service.properties.endpoint,
            'key': keys.key1,
            'kind': service.kind
        }
    except Exception as e:
        logger.error(f"Cognitive Services (all-in-one) の取得中にエラーが発生しました: {str(e)}")
        return {}

def get_subscription_id():
    """Azure CLIからサブスクリプションIDを取得する"""
    try:
        cmd = "az account show --query id -o tsv"
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except Exception as e:
        raise ValueError(f"サブスクリプションIDの取得に失敗しました: {str(e)}")

def main():
    args = parse_args()
    
    # 出力ファイルが既に存在し、--forceオプションが指定されていない場合はエラー
    if os.path.exists(args.output) and not args.force:
        logger.error(f"出力ファイル '{args.output}' は既に存在します。--force オプションを使用して上書きしてください。")
        return 1
    
    # AzureのSDKクライアントを初期化
    clients = {}
    try:
        credential = DefaultAzureCredential()
        subscription_id = get_subscription_id()
        
        clients = {
            'resource': ResourceManagementClient(credential, subscription_id),
            'storage': StorageManagementClient(credential, subscription_id),
            'search': SearchManagementClient(credential, subscription_id),
            'cognitive': CognitiveServicesManagementClient(credential, subscription_id)
        }
        
        logger.info(f"Azure SDKの初期化が完了しました")
        logger.info(f"サブスクリプションID: {subscription_id}")
    except Exception as e:
        logger.error(f"Azure SDKの初期化中にエラーが発生しました: {str(e)}")
        return 1
    
    # リソースグループが存在するか確認
    try:
        clients['resource'].resource_groups.get(args.resource_group)
        logger.info(f"リソースグループ '{args.resource_group}' が見つかりました")
    except Exception as e:
        logger.error(f"リソースグループ '{args.resource_group}' が見つかりません: {str(e)}")
        return 1
    
    # 各サービスの情報を取得
    storage = get_storage_account(clients, args.resource_group)
    search = get_search_service(clients, args.resource_group)
    openai = get_openai_service(clients, args.resource_group)
    
    # コマンドライン引数で指定された場合は、自動検出の結果より優先する
    if openai and args.chat_model:
        openai['CHAT_MODEL'] = args.chat_model
    
    if openai and args.chat_deployment:
        openai['AZURE_OPENAI_CHAT_DEPLOYMENT'] = args.chat_deployment
    
    if openai and args.embedding_model:
        openai['EMBEDDING_MODEL'] = args.embedding_model
    
    if openai and args.embedding_deployment:
        openai['AZURE_OPENAI_EMBEDDING_DEPLOYMENT'] = args.embedding_deployment
    
    # 外部モデル情報の取得
    external_models = []
    
    # 1. コマンドラインで指定された場合
    if args.external_endpoint and args.external_key and args.external_deployment:
        external_models.append({
            "name": args.external_model or "external-embedding-model",
            "endpoint": args.external_endpoint,
            "deployment": args.external_deployment,
            "api_key": args.external_key,
            "api_version": args.external_api_version,
            "languages": ["ja", "en", "zh", "fr", "de", "es"]
        })
    
    # 2. 設定ファイルが指定された場合
    elif args.external_config:
        config = load_external_config(args.external_config)
        if config and "embedding_models" in config:
            external_models.extend(config["embedding_models"])
    
    # 外部モデルのアクセス確認
    valid_external_models = []
    for model in external_models:
        if check_external_model(
            model["endpoint"],
            model["api_key"],
            model["deployment"],
            model["api_version"]
        ):
            valid_external_models.append(model)
    
    # Cognitive Services (all-in-one) の情報を取得
    cognitive_allinone = get_cognitive_services_allinone(clients, args.resource_group)
    
    # 環境変数ファイルを生成
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        # Azure環境変数
        f.write("# Azure Environment Variables\n")
        f.write(f"AZURE_RESOURCE_GROUP={args.resource_group}\n\n")
        
        # ストレージアカウント情報
        if storage:
            f.write("# Storage Account\n")
            f.write(f"AZURE_STORAGE_ACCOUNT={storage['name']}\n")
            f.write(f"AZURE_STORAGE_KEY=\"{storage['key']}\"\n")
            f.write(f"AZURE_STORAGE_CONNECTION_STRING=\"{storage['connection_string']}\"\n\n")
        
        # Search サービス情報
        if search:
            f.write("# Search Service\n")
            f.write(f"AZURE_SEARCH_SERVICE_NAME={search['name']}\n")
            f.write(f"AZURE_SEARCH_SERVICE_ENDPOINT={search['endpoint']}\n")
            f.write(f"AZURE_SEARCH_SERVICE_KEY={search['key']}\n")
            f.write(f"AZURE_SEARCH_ENDPOINT={search['endpoint']}\n")
            f.write(f"AZURE_SEARCH_ADMIN_KEY={search['key']}\n\n")
        
        # OpenAI サービス情報
        if openai:
            f.write("# OpenAI Service\n")
            f.write(f"AZURE_OPENAI_SERVICE_NAME={openai['AZURE_OPENAI_SERVICE']}\n")
            f.write(f"AZURE_OPENAI_SERVICE_ENDPOINT={openai['AZURE_OPENAI_ENDPOINT']}\n")
            f.write(f"AZURE_OPENAI_ENDPOINT={openai['AZURE_OPENAI_ENDPOINT']}\n")
            f.write(f"AZURE_OPENAI_API_KEY={openai['AZURE_OPENAI_API_KEY']}\n")
            f.write(f"AZURE_OPENAI_API_VERSION={openai['AZURE_OPENAI_API_VERSION']}\n\n")
            
            if openai['CHAT_MODEL']:
                f.write(f"CHAT_MODEL={openai['CHAT_MODEL']}\n")
                f.write(f"AZURE_OPENAI_CHAT_DEPLOYMENT={openai['AZURE_OPENAI_CHAT_DEPLOYMENT']}\n")
            
            if openai['EMBEDDING_MODEL']:
                f.write(f"EMBEDDING_MODEL={openai['EMBEDDING_MODEL']}\n")
                f.write(f"AZURE_OPENAI_EMBEDDING_DEPLOYMENT={openai['AZURE_OPENAI_EMBEDDING_DEPLOYMENT']}\n")
            
            f.write("\n")
        
        # Cognitive Services (all-in-one) 情報
        if cognitive_allinone:
            f.write("# Cognitive Services (all-in-one)\n")
            f.write(f"AZURE_COGNITIVE_ALLINONE_NAME={cognitive_allinone['name']}\n")
            f.write(f"AZURE_COGNITIVE_ALLINONE_ENDPOINT={cognitive_allinone['endpoint']}\n")
            f.write(f"AZURE_COGNITIVE_ALLINONE_KEY=\"{cognitive_allinone['key']}\"\n")
            f.write(f"AZURE_COGNITIVE_ALLINONE_KIND={cognitive_allinone['kind']}\n\n")
        
        # 外部モデル情報
        if valid_external_models:
            f.write("# External Models\n")
            for i, model in enumerate(valid_external_models):
                # 最初のモデルを主なエンベディングモデルとして設定
                if i == 0:
                    f.write(f"EMBEDDING_MODEL={model['name']}\n")
                    f.write(f"AZURE_OPENAI_EMBEDDING_DEPLOYMENT={model['deployment']}\n")
                    f.write(f"EMBEDDING_API_BASE={model['endpoint']}\n")
                    f.write(f"EMBEDDING_API_KEY={model['api_key']}\n")
                    f.write(f"EMBEDDING_API_VERSION={model['api_version']}\n\n")
                
                # 言語別モデルの設定
                for lang in model.get("languages", []):
                    f.write(f"AZURE_OPENAI_EMBEDDING_{lang.upper()}={model['deployment']}\n")
    
    logger.info(f"環境変数ファイル '{args.output}' を生成しました")
    return 0

if __name__ == '__main__':
    exit(main()) 