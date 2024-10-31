from flask import Flask, request, jsonify
from flask_cors import CORS  # 导入 CORS


import json
import hashlib
import subprocess
import zipfile
import os

from minio import Minio
from minio.error import S3Error

import mysql.connector
from mysql.connector import Error


app = Flask(__name__)
# 允许所有域名访问
CORS(app)


@app.route('/predict', methods=['POST'])
def predict():
    try:
        # 从请求中获取数据
        data = request.get_json()
        toolInfo = data["toolType"]
        fileId = data["fileId"]

        ############################# 构建用户选择审计工具列表 #################################
        detectors = 'default'
        if(len(toolInfo) > 0):
            detectors = ', '.join([item['label'] for item in toolInfo])


        try:
            # 连接到MySQL数据库
            connection = mysql.connector.connect(
                host='101.42.49.16',  # 数据库主机地址
                database='db_sb4u',  # 数据库名称
                user='root',  # 数据库用户名
                password='root'  # 数据库密码
            )

            if connection.is_connected():
                # 创建cursor对象
                cursor = connection.cursor()

                # SQL查询语句
                sql = "SELECT bucket, file_path, filename, file_type FROM t_media_files WHERE id = %s"

                # 要查询的id值
                media_id = (fileId,)  # 假设我们要查询id为123的记录

                # 执行SQL查询
                cursor.execute(sql, media_id)

                # 获取查询结果
                result = cursor.fetchone()  # 使用fetchone()获取单条记录

                # 检查结果并接收字段
                if result:
                    bucket, file_path, filename, fileType = result
                    print(f"Bucket: {bucket}, File Path: {file_path}")
                else:
                    print("No record found.")

                # 关闭cursor
                cursor.close()

        except Error as e:
            print("Error while connecting to MySQL", e)

        finally:
            # 关闭数据库连接
            if connection.is_connected():
                connection.close()
                print("MySQL connection is closed")

        print("开始下载")

        # MinIO服务的URL和访问凭证
        minio_client = Minio(
            "101.42.49.16:9001",  # MinIO服务的URL
            access_key="admin",  # MinIO的access key
            secret_key="admin",  # MinIO的secret key
            secure=False  # 使用https
        )

        print("Minio client created success")

        # 存储桶名称和要下载的文件名称
        bucket_name = bucket
        object_name = file_path

        try:
            # 使用 MinIO 的 fetch_object 方法下载文件
            minio_client.fget_object(
                bucket_name,
                object_name,
                file_path
            )
            print(f"'{object_name}' has been downloaded to '{file_path}'.")
        except S3Error as exc:
            print("Error occurred: ", exc)

        ############################################    执行合约审计   ##############################################

        # 要运行的Python文件路径
        python_file_path = 'elysium.py'

        solidity_file_path = '../elysium/' + file_path



        # 调用命令行来运行Python文件
        # 这里使用了subprocess.run()，它是Python 3.5+版本中推荐的方式
        try:
            print("开始检测....")
            # 调用命令行来运行Python文件，并传递参数
            if fileType == '.sol':
                print("源码检测模式")
                if detectors == 'default':
                    args = ['python3', python_file_path, '-s', solidity_file_path, '--cfg']
                else:
                    args = ['python3', python_file_path, '-s', solidity_file_path, '--cfg']
            else:
                print("字节码检测模式")
                if detectors == 'default':
                    args = ['python3', python_file_path, '-b', solidity_file_path, '--cfg']
                else:
                    args = ['python3', python_file_path, '-b', solidity_file_path, '--cfg']
            print("构建的命令行参数：" + str(args))
            result = subprocess.run(args, check=False, text=True, capture_output=True)
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            print("检测结束")
        except subprocess.CalledProcessError as e:
            print(f"Error: {e}")

        json_file_path = '../elysium/' + file_path[:-4] + ".bugs.json"

        print(json_file_path)

        ###############################################   将结果上传到minio ###########################################
        # 要压缩的目录路径
        directory_to_zip = '../elysium/' + file_path.rsplit('/', 1)[0]

        # 压缩文件的名称
        zip_filename = os.path.join(directory_to_zip, fileId + '.results.zip')

        # 要排除的文件扩展名列表
        exclude_extensions = {'.sol','.bin'}  # 排除.sol和.bin文件

        # 动态构建文件列表
        file_paths = []
        for root, dirs, files in os.walk(directory_to_zip):
            for file in files:
                # 获取文件的扩展名
                _, ext = os.path.splitext(file)
                # 如果文件的扩展名不在排除列表中，则添加到文件列表
                if ext not in exclude_extensions:
                    file_path = os.path.join(root, file)
                    file_paths.append(file_path)

        # 创建一个ZipFile对象，用于写入ZIP文件
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 遍历文件路径列表
            for file_path in file_paths:
                # 确保文件存在
                if os.path.isfile(file_path):
                    # 获取文件的basename，作为ZIP中的文件名
                    file_name = os.path.basename(file_path)
                    # 将文件添加到zip文件中
                    zipf.write(file_path, file_name)
                else:
                    print(f"文件 {file_path} 不存在，跳过。")

        print(f"文件已压缩到 {zip_filename}")


        ###################   zip  md5 ############################
        def get_md5(file_path):
            # 创建md5对象
            md5 = hashlib.md5()
            # 打开文件，读取内容，并更新md5对象
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    md5.update(chunk)
            # 获取16进制的md5值
            return md5.hexdigest()

        # 桶是否存在 不存在则新建
        bucket_name = 'detectresult'
        file_name = fileId + '/' + detectors + '/' +  fileId +  '.results.zip'
        local_path = zip_filename

        check_bucket = minio_client.bucket_exists(bucket_name)
        if not check_bucket:
            minio_client.make_bucket(bucket_name)

        try:
            minio_client.fput_object(bucket_name=bucket_name,
                                         object_name=file_name,
                                         file_path=local_path)
        except FileNotFoundError as err:
            print('upload_failed: ' + str(err))
        except S3Error as err:
            print("upload_failed:", err)





        ##########################  构建文件保存到数据库的信息 ###########################
        # 创建一个DTO对象来存储文件信息
        class UploadFileParamsDto:
            def __init__(self, id, filename, bucket, filePath, fileId, fileSize, fileType):
                self.filename = filename
                self.fileSize = fileSize
                self.id = id
                self.bucket = bucket
                self.filePath = filePath
                self.fileId = fileId
                self.fileType = fileType

        # 获取文件大小
        result_file_size = os.path.getsize(zip_filename)
        # 计算并打印MD5值
        md5_value = get_md5(zip_filename)
        print(f"The MD5 value of the file is: {md5_value}")
        result_id = md5_value
        reslut_filename = fileId + '.results.zip'
        result_bucket = 'detectresult'
        result_filepath = file_name
        result_fileid = fileId
        result_type = '.zip'

        # 创建DTO实例
        upload_file_params_dto = UploadFileParamsDto(
            id = result_id,
            filename = reslut_filename,
            bucket = result_bucket,
            filePath = result_filepath,
            fileId = result_fileid,
            fileSize= result_file_size,
            fileType= result_type
        )

        # 将DTO对象转换为JSON
        upload_file_params_json = json.dumps(upload_file_params_dto.__dict__, ensure_ascii=False)
        print('#################' + upload_file_params_json + '######################')

        # 要更新的键名映射
        key_mapping = {
            'code_coverage': 'codeCoverage',
            'execution_time': 'executionTime'
        }


        try:
            # 打开并读取JSON文件
            with open(json_file_path, 'r') as file:
                data = file.read()
                data_list = json.loads(data)  # 假设这是一个列表

                # 检查是否为列表
                if isinstance(data_list, list):
                    for item in data_list:
                        # 更新每个item中的键名
                        for old_key, new_key in key_mapping.items():
                            if old_key in item:
                                item[new_key] = item.pop(old_key)
                                # 如果还需要更新其他字段，可以在这里继续添加代码
                                # 例如：item['newFieldName'] = 'newValue'
                        # 设置contractName字段
                        item['contractName'] = filename
                else:
                    # 如果不是列表，那么假定它是一个字典，并直接更新键名
                    for old_key, new_key in key_mapping.items():
                        if old_key in data_list:
                            data_list[new_key] = data_list.pop(old_key)
                    # 设置contractName字段
                    data_list['contractName'] = filename

                #######  保存到数据库的信息  #################

                # 将数据以JSON格式返回给前端
                return jsonify({"success": True, "code": 20000, "message": "成功", "data": {"res": data_list, "uploadFileParamsDto": upload_file_params_json}})
        except FileNotFoundError:
            # 如果文件不存在，返回错误信息
            return jsonify({"success": False, "code": 404, "message": "审计结果文件不存在"})
        except json.JSONDecodeError:
            # 如果JSON格式不正确，返回错误信息
            return jsonify({"success": False, "code": 400, "message": "审计结果文件格式错误"})




    except Exception as e:
        return jsonify({"success": False, "code": 9999, "message": str(e)})
    finally:
        cursor.close()
        connection.close()

        with os.scandir(directory_to_zip) as entries:
            for entry in entries:
                if entry.is_file() and not (entry.name.endswith('.sol') or entry.name.endswith('.bin')):
                    file_path = entry.path
                    os.remove(file_path)
                    print(f"Deleted file: {file_path}")





    app.run(debug=True)
if __name__ == '__main__':
    app.run(debug=True)
