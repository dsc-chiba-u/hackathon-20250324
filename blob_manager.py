#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Azure Blobストレージの操作とAzure AI Search検索を統合したスクリプト
以下の機能を提供します：
- ファイルのアップロード (upload)
- ファイルのダウンロード (download)
- Blobの一覧表示 (list)
- Blobの削除 (delete)
- ディレクトリの削除 (delete-directory)
- ディレクトリのクリア後アップロード (clear-and-upload)
- ドキュメントの検索 (search) - Azure AI Search
"""

import os
import json
import argparse
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

# 標準出力のバッファリングを無効化（確実に出力を表示するため）
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# .envファイルから環境変数を読み込む
load_dotenv()

# ロガーの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BlobManager:
    def __init__(self, connection_string=None, container_name=None, debug_mode=False):
        """
        Blobマネージャーの初期化
        
        Args:
            connection_string: Azure Blobストレージの接続文字列
            container_name: Blobコンテナ名
            debug_mode: デバッグモードの有効/無効（詳細なログ出力）
        """
        self.connection_string = connection_string or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not self.connection_string:
            raise ValueError("接続文字列が指定されていません。パラメータまたは環境変数AZURE_STORAGE_CONNECTION_STRINGを設定してください。")
            
        self.container_name = container_name or os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "documents")
        self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
        self.uploaded_files = []
        self.debug_mode = debug_mode
        
        # デバッグモードが有効な場合、詳細なログを表示
        if self.debug_mode:
            logging.getLogger('azure').setLevel(logging.DEBUG)
            logging.getLogger().setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logging.getLogger().addHandler(console_handler)
            
            logger.debug(f"デバッグモードで実行中: コンテナ '{self.container_name}'")
        
        # 検索関連の初期化
        self.search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        self.search_key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
        self.default_index_name = os.environ.get("UNIFYD_INDEX_NAME", "unifyd-docs-index")
    
    def ensure_container_exists(self):
        """コンテナが存在することを確認し、存在しない場合は作成します"""
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            container_client.get_container_properties()
            print(f"ℹ️  コンテナ '{self.container_name}' は既に存在します")
        except Exception:
            self.blob_service_client.create_container(self.container_name)
            print(f"✅ コンテナ '{self.container_name}' を作成しました")
    
    def get_content_settings(self, file_path):
        """ファイルの拡張子に基づいた適切なContentSettingsを返す"""
        file_extension = Path(file_path).suffix.lower()
        content_type = None

        # ファイルタイプごとにContent-Typeを設定
        if file_extension == '.pdf':
            content_type = "application/pdf"
        elif file_extension == '.csv':
            content_type = "text/csv"
        elif file_extension == '.json':
            content_type = "application/json"
        elif file_extension == '.txt':
            content_type = "text/plain"
        elif file_extension == '.html':
            content_type = "text/html"
        elif file_extension in ['.jpg', '.jpeg']:
            content_type = "image/jpeg"
        elif file_extension == '.png':
            content_type = "image/png"
        elif file_extension == '.docx':
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif file_extension == '.xlsx':
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif file_extension == '.pptx':
            content_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        
        # Content-Typeが設定できない場合はNoneを返す
        if content_type:
            return ContentSettings(content_type=content_type)
        return None
    
    def upload_file(self, local_file_path, blob_path=None, content_settings=None):
        """
        ローカルファイルをBlobストレージにアップロードします
        
        Args:
            local_file_path: アップロードするローカルファイルのパス
            blob_path: Blobストレージ内での保存先パス（完全なパス）。指定しない場合はファイル名のみ使用
            content_settings: Blobのコンテンツ設定
            
        Returns:
            dict: アップロードされたファイルの情報を含む辞書、失敗時はNone
        """
        try:
            # ファイルの存在確認
            file_path = Path(local_file_path)
            if not file_path.exists():
                print(f"❌ ファイルが見つかりません: {local_file_path}")
                return None
                
            # ファイルサイズの確認
            file_size = file_path.stat().st_size
            
            # Blobの名前を決定
            if blob_path:
                # blobパスが直接指定された場合はそのまま使用
                blob_name = blob_path
            else:
                # 指定がない場合はファイル名をそのまま使用（日本語名も保持）
                blob_name = file_path.name
            
            # コンテナの存在確認
            self.ensure_container_exists()
            
            # Blobクライアントの取得
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            # コンテンツ設定が指定されていない場合は、ファイルの拡張子に基づいて自動決定
            if content_settings is None:
                content_settings = self.get_content_settings(local_file_path)
                
            # ファイルサイズに基づいて処理方法を決定（大きなファイルの場合はチャンクアップロード）
            with open(local_file_path, "rb") as data:
                if content_settings:
                    blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
                else:
                    blob_client.upload_blob(data, overwrite=True)
            
            # アップロード情報を作成
            file_info = {
                'name': file_path.stem,
                'url': blob_client.url,
                'path': str(file_path),
                'size': file_size,
                'type': file_path.suffix.lower()[1:] if file_path.suffix else "",  # 拡張子（.を除く）
                'blob_name': blob_name
            }
            
            # アップロード履歴に追加
            self.uploaded_files.append(file_info)
            
            # アップロード成功メッセージ
            print(f"✅ ファイル '{local_file_path}' ({file_size:,} バイト) を '{blob_name}' としてアップロードしました")
            
            # アップロード後の確認（オプション）
            try:
                # アップロードされたBlobのプロパティを取得して確認
                properties = blob_client.get_blob_properties()
                if properties.size == file_size:
                    print(f"✓ アップロード検証成功: サイズ一致 ({properties.size:,} バイト)")
                else:
                    print(f"⚠️ アップロード検証警告: サイズ不一致 (ローカル: {file_size:,} バイト, リモート: {properties.size:,} バイト)")
            except Exception as ve:
                print(f"⚠️ アップロード検証中にエラーが発生しました: {str(ve)}")
            
            return file_info
            
        except Exception as e:
            print(f"❌ アップロード中にエラーが発生しました: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def download_file(self, blob_name, local_file_path):
        """Blobストレージからファイルをダウンロードします"""
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name
        )
        
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        with open(local_file_path, "wb") as download_file:
            download_file.write(blob_client.download_blob().readall())
        
        print(f"✅ Blob '{blob_name}' を '{local_file_path}' にダウンロードしました")
        return local_file_path
    
    def download_blob(self, blob_name, output_path=None):
        """Blobをダウンロードします"""
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name
        )
        
        try:
            # 出力パスが指定されていない場合、現在のディレクトリにダウンロード
            if not output_path:
                output_path = Path(blob_name).name
            
            # ディレクトリが存在しない場合は作成
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Blobをダウンロード
            with open(output_path, "wb") as file:
                file.write(blob_client.download_blob().readall())
            
            print(f"✅ Blob '{blob_name}' を '{output_path}' にダウンロードしました")
            return True
        except Exception as e:
            print(f"❌ Blobのダウンロードに失敗しました: {str(e)}")
            return False
    
    def download_blob_to_string(self, blob_name, container_name=None):
        """Blobの内容を文字列として取得します（エンコーディングを自動検出）
        
        Args:
            blob_name: ダウンロードするBlobの名前
            container_name: Blobが格納されているコンテナ名（省略時はデフォルトコンテナ）
            
        Returns:
            str: Blobの内容を文字列として返す
        """
        container = container_name or self.container_name
        blob_client = self.blob_service_client.get_blob_client(
            container=container,
            blob=blob_name
        )
        
        try:
            # Blobの内容をバイトデータとして取得
            blob_data = blob_client.download_blob().readall()
            
            # エンコーディングを自動検出
            import chardet
            result = chardet.detect(blob_data)
            encoding = result['encoding']
            confidence = result['confidence']
            
            print(f"Blob '{blob_name}' のエンコーディングを検出: {encoding} (確信度: {confidence:.2f})")
            
            # 検出されたエンコーディングでデコード
            content = blob_data.decode(encoding or 'utf-8', errors='replace')
            return content
            
        except Exception as e:
            print(f"❌ Blobの読み込みに失敗しました: {str(e)}")
            return None
    
    def list_blobs(self, prefix=None, format_type='table', show_details=False):
        """コンテナ内のBlobを一覧表示します
        
        Args:
            prefix: フィルタリングするプレフィックス
            format_type: 出力形式 ('table', 'list', 'json')
            show_details: 詳細情報（サイズ、タイプなど）を表示するかどうか
        """
        container_client = self.blob_service_client.get_container_client(self.container_name)
        
        print(f"コンテナ '{self.container_name}' の内容:")
        if prefix:
            print(f"プレフィックス: {prefix}")
        
        blob_count = 0
        blob_list = []
        blob_details = []
        
        # ファイルタイプごとの統計
        file_type_stats = {}
        total_size = 0
        
        for blob in container_client.list_blobs(name_starts_with=prefix):
            blob_list.append(blob.name)
            blob_count += 1
            total_size += blob.size
            
            # ファイルタイプの統計を取得
            file_ext = Path(blob.name).suffix.lower()
            if file_ext:
                file_type = file_ext[1:]  # 先頭の'.'を除去
                if file_type in file_type_stats:
                    file_type_stats[file_type] += 1
                else:
                    file_type_stats[file_type] = 1
            
            # 詳細情報を保存
            blob_details.append({
                'name': blob.name,
                'size': blob.size,
                'type': Path(blob.name).suffix.lower()[1:] if Path(blob.name).suffix else "",
                'last_modified': blob.last_modified.strftime('%Y-%m-%d %H:%M:%S') if hasattr(blob, 'last_modified') else 'N/A'
            })
        
        # 出力形式に基づいて表示
        if blob_count == 0:
            print("  コンテナは空です")
        else:
            if format_type == 'table':
                # テーブル形式で表示
                if show_details:
                    # ヘッダー
                    print("\n{:<60} {:<12} {:<8} {:<20}".format("ファイル名", "サイズ(B)", "タイプ", "最終更新日時"))
                    print("-" * 100)
                    
                    # 各Blobの情報を表示
                    for blob in blob_details:
                        print("{:<60} {:<12} {:<8} {:<20}".format(
                            blob['name'][:57] + "..." if len(blob['name']) > 60 else blob['name'],
                            blob['size'],
                            blob['type'],
                            blob['last_modified']
                        ))
                else:
                    # シンプル表示
                    for blob_name in blob_list:
                        print(f"  - {blob_name}")
            
            elif format_type == 'list':
                # シンプルなリスト形式
                for blob_name in blob_list:
                    print(blob_name)
            
            elif format_type == 'json':
                # JSON形式（詳細情報を含む）
                import json
                print(json.dumps(blob_details, indent=2))
            
            # 統計情報
            print(f"\n合計: {blob_count} ファイル, {total_size:,} バイト")
            
            if file_type_stats and show_details:
                print("\nファイルタイプ別統計:")
                for file_type, count in sorted(file_type_stats.items(), key=lambda x: x[1], reverse=True):
                    print(f"  - {file_type}: {count} ファイル")
        
        return blob_list
    
    def get_blob_info(self, blob_name):
        """Blobの情報を取得します"""
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name
        )
        
        # ファイル名と拡張子の抽出
        path = Path(blob_name)
        file_info = {
            'name': path.stem,
            'url': blob_client.url,
            'path': blob_name,  # blobのパス
            'type': path.suffix.lower()[1:] if path.suffix else "",  # 拡張子（.を除く）
            'blob_name': blob_name
        }
        
        return file_info
    
    def get_all_blobs_info(self, prefix=None):
        """コンテナ内のすべてのBlobの情報を取得します"""
        blobs = self.list_blobs(prefix)
        return [self.get_blob_info(blob) for blob in blobs]
    
    def delete_blob(self, blob_name):
        """Blobを削除します"""
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name
        )
        
        try:
            blob_client.delete_blob()
            print(f"🗑️  Blob '{blob_name}' を削除しました")
            return True
        except Exception as e:
            print(f"❌ Blobの削除に失敗しました: {str(e)}")
            return False
    
    def delete_directory(self, prefix=None):
        """指定されたプレフィックス（ディレクトリ）配下の全ファイルを削除します"""
        deleted_count = 0
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            
            # プレフィックスに一致するBlobを一覧取得
            blobs = [blob.name for blob in container_client.list_blobs(name_starts_with=prefix)]
            
            # 各Blobを削除
            for blob_name in blobs:
                self.delete_blob(blob_name)
                deleted_count += 1
            
            return deleted_count
        except Exception as e:
            print(f"❌ ディレクトリの削除中にエラーが発生しました: {str(e)}")
            return deleted_count
    
    def upload_directory(self, local_dir, blob_prefix=None):
        """ディレクトリ内のすべてのファイルをアップロードします"""
        uploaded_files = []
        local_path = Path(local_dir)
        
        if not local_path.exists():
            print(f"❌ ディレクトリが存在しません: {local_dir}")
            return uploaded_files
        
        # ディレクトリ名をプレフィックスに使用（指定がなければ）
        if blob_prefix is None:
            blob_prefix = local_path.name
        
        for file_path in local_path.glob("**/*.*"):  # サブディレクトリも含めて再帰的に検索
            if file_path.is_file():
                # フォルダ構造を維持するための相対パス計算
                relative_path = file_path.relative_to(local_path)
                blob_sub_path = str(relative_path).replace("\\", "/")
                full_blob_prefix = f"{blob_prefix}/{blob_sub_path}"
                dir_name = os.path.dirname(full_blob_prefix)
                
                file_info = self.upload_file(str(file_path), dir_name)
                if file_info:
                    uploaded_files.append(file_info)
        
        print(f"✅ ディレクトリ '{local_dir}' から {len(uploaded_files)} ファイルをアップロードしました")
        return uploaded_files

    def search_documents(self, index_name, query, top=10, filter_expr=None, select=None, output_format='pretty'):
        """Azure AI Searchインデックスに対してクエリを実行する

        Args:
            index_name: 検索対象のインデックス名
            query: 検索クエリ
            top: 返す結果の最大数（デフォルト: 10）
            filter_expr: フィルター式（例: "category eq 'Books'"）
            select: 返すフィールドの指定（カンマ区切り、例: "id,title,description"）
            output_format: 出力形式（'pretty', 'json', 'compact'）

        Returns:
            検索結果のリスト
        """
        try:
            if not self.search_endpoint or not self.search_key:
                logger.error("環境変数 AZURE_SEARCH_ENDPOINT または AZURE_SEARCH_ADMIN_KEY が設定されていません")
                return []
            
            # SearchClientの初期化
            credential = AzureKeyCredential(self.search_key)
            client = SearchClient(endpoint=self.search_endpoint,
                                 index_name=index_name,
                                 credential=credential)
            
            # 検索オプションの設定
            search_options = {
                "top": top,
                "include_total_count": True
            }
            
            if filter_expr:
                search_options["filter"] = filter_expr
            
            if select:
                search_options["select"] = select.split(",")
            
            # 検索実行
            results = client.search(search_text=query, **search_options)
            
            # 結果の表示
            total_count = results.get_count()
            logger.info(f"検索結果: {total_count} 件見つかりました")
            
            # 結果をリストに変換
            docs = list(results)
            
            # 出力形式に基づいて結果を表示
            if output_format == 'json':
                # JSON形式（整形あり）
                print(json.dumps([dict(doc) for doc in docs], ensure_ascii=False, indent=2))
            elif output_format == 'compact':
                # コンパクト表示（一行ごとにJSONオブジェクト）
                for doc in docs:
                    print(json.dumps(dict(doc), ensure_ascii=False))
            else:
                # デフォルト: 整形表示
                for i, doc in enumerate(docs):
                    logger.info(f"\n===== ドキュメント {i+1} =====")
                    
                    # ドキュメントの内容を表示（整形版）
                    doc_json = json.dumps(doc, ensure_ascii=False, indent=2)
                    print(doc_json)
            
            return docs
        
        except Exception as e:
            logger.error(f"検索中にエラーが発生しました: {str(e)}")
            return []

def parse_args():
    parser = argparse.ArgumentParser(description="Azure Blob Storage 管理ツール")
    parser.add_argument("--action", choices=[
        "download", "list", "delete", "delete-directory", 
        "clear-and-upload", "upload", "upload-file", "convert-pdf", "get-headers", "search"], 
        required=True, help="実行するアクション")
    parser.add_argument("--container", help="Blobコンテナ名 (デフォルト: 環境変数から取得、または 'documents')")
    parser.add_argument("--path", help="アップロード/ダウンロード対象のファイルまたはディレクトリパス")
    parser.add_argument("--prefix", help="Blobストレージ内のプレフィックス（フォルダパス）", default=None)
    parser.add_argument("--blob-name", help="ダウンロードまたは削除対象のBlob名", default=None)
    parser.add_argument("--output", help="ダウンロード先のローカルパス", default="./downloaded")
    parser.add_argument("--format", choices=["table", "list", "json", "pretty", "compact"], default="table", help="出力形式 (デフォルト: table)")
    parser.add_argument("--details", action="store_true", help="リスト表示時に詳細情報を表示する")
    parser.add_argument("--env-file", help="環境変数ファイルのパス (.env形式)", default=None)
    parser.add_argument("--debug-mode", action="store_true", help="デバッグモードを有効化（詳細なログ出力）")
    
    # 検索関連の引数
    parser.add_argument("--index-name", help="検索対象のインデックス名 (デフォルト: unifyd-docs-index)", default=None)
    parser.add_argument("--query", help="検索クエリ", default=None)
    parser.add_argument("--top", type=int, help="取得する最大件数", default=10)
    parser.add_argument("--filter", help="検索結果のフィルタ条件", default=None)
    parser.add_argument("--select", help="取得するフィールドをカンマ区切りで指定", default=None)
    
    return parser.parse_args()

def main():
    try:
        args = parse_args()
        
        # 環境変数ファイルを読み込む（指定がある場合）
        if args.env_file:
            if os.path.exists(args.env_file):
                print(f"環境変数ファイル '{args.env_file}' を読み込みます")
                load_dotenv(args.env_file)
            else:
                print(f"❌ 環境変数ファイル '{args.env_file}' が見つかりません")
                return 1
        
        # Blob Managerを初期化
        blob_manager = BlobManager(
            connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
            container_name=args.container or os.getenv("AZURE_STORAGE_CONTAINER_NAME", "documents"),
            debug_mode=args.debug_mode
        )
        
        # 各アクションに応じた処理
        if args.action == "download":
            if not args.blob_name and not args.prefix:
                print("エラー: --blob-name または --prefix を指定してください")
                return
            blob_manager.download_file(args.blob_name, args.output)
        elif args.action == "list":
            blob_manager.list_blobs(args.prefix, args.format, args.details)
        elif args.action == "delete":
            if not args.blob_name:
                print("エラー: --blob-name を指定してください")
                return
            blob_manager.delete_blob(args.blob_name)
        elif args.action == "delete-directory":
            if not args.prefix:
                print("エラー: --prefix を指定してください")
                return
            blob_manager.delete_directory(args.prefix)
        elif args.action == "clear-and-upload":
            if not args.path:
                print("エラー: --path を指定してください")
                return
            blob_manager.clear_container()
            if os.path.isdir(args.path):
                blob_manager.upload_directory(args.path, args.prefix)
            else:
                print(f"❌ ディレクトリではありません: {args.path}")
        elif args.action == "upload":
            if not args.path:
                print("エラー: --path を指定してください")
                return
            if os.path.isdir(args.path):
                blob_manager.upload_directory(args.path, args.prefix)
            else:
                print(f"❌ ディレクトリではありません: {args.path}")
        elif args.action == "upload-file":
            if not args.path:
                print("エラー: --path を指定してください")
                return 1
            
            # ファイルの存在確認
            if not os.path.isfile(args.path):
                print(f"❌ ファイルではありません: {args.path}")
                return 1
                
            print(f"単一ファイル '{args.path}' のアップロードを開始します...")
            
            # 単一ファイルのアップロード
            result = blob_manager.upload_file(args.path, args.prefix)
            
            # アップロード結果の表示
            if result:
                print(f"✅ アップロード完了: '{result['blob_name']}'")
                
                # アップロードされたファイルの情報
                print("\nアップロード情報:")
                print(f"  ファイル名: {os.path.basename(args.path)}")
                print(f"  保存先: {result['blob_name']}")
                print(f"  サイズ: {result['size']:,} バイト")
                print(f"  コンテナ: {args.container or blob_manager.container_name}")
                print(f"  URL: {result['url']}")
                
                return 0
            else:
                print(f"❌ アップロードに失敗しました: {args.path}")
                return 1
        elif args.action == "convert-pdf":
            if not args.path:
                print("エラー: --path を指定してください")
                return
            convert_pdf_to_images(args.path, args.output)
        elif args.action == "get-headers":
            if not args.blob_name:
                print("エラー: --blob-name を指定してください")
                return
            headers = blob_manager.get_blob_headers(args.blob_name)
            print(json.dumps(headers, indent=2, ensure_ascii=False))
        elif args.action == "search":
            if not args.query:
                print("エラー: --query を指定してください")
                return
            index_name = args.index_name or blob_manager.default_index_name
            blob_manager.search_documents(index_name, args.query, args.top, args.filter, args.select, args.format)
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")
        return 1

if __name__ == "__main__":
    exit(main()) 