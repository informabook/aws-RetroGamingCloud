import boto3
import json
import os
import base64
import time
from botocore.exceptions import ClientError

ec2 = boto3.client('ec2')
s3 = boto3.client('s3')

# --- CONFIG ---
AMI_ID = 'ami-065564df1f27065d9' # TON AMI ID
INSTANCE_TYPE = 't3.small'
SSH_KEY_NAME = 'kp-retro'
# --------------

CORE_MAP = {
    '.nes': 'nestopia', '.sfc': 'snes9x', '.smc': 'snes9x',
    '.gba': 'mgba', '.gb': 'gambatte', '.gbc': 'gambatte',
    '.md': 'genesis_plus_gx', '.iso': 'pcsx_rearmed', '.cue': 'pcsx_rearmed'
}

def lambda_handler(event, context):
    headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'OPTIONS,POST,GET', 'Content-Type': 'application/json' }
    
    # GET (Catalogue)
    if event['httpMethod'] == 'GET':
        try:
            bucket = os.environ['ROMS_BUCKET']
            params = event.get('queryStringParameters') or {}
            prefix = params.get('path', '') 
            if prefix and not prefix.endswith('/'): prefix += '/'

            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter='/')
            contents = []
            for p in response.get('CommonPrefixes', []):
                contents.append({'type': 'folder', 'name': p['Prefix'].replace(prefix, '', 1).strip('/'), 'path': p['Prefix']})
            for o in response.get('Contents', []):
                if not o['Key'].endswith('/'): contents.append({'type': 'file', 'name': o['Key'].replace(prefix, '', 1), 'path': o['Key']})

            return { 'statusCode': 200, 'headers': headers, 'body': json.dumps(contents) }
        except Exception as e:
            return { 'statusCode': 500, 'headers': headers, 'body': json.dumps({'error': str(e)}) }

    # POST (Lancement)
    if event['httpMethod'] == 'POST':
        try:
            body = json.loads(event['body'])
            rom_key = body.get('rom')
            if not rom_key: return {'statusCode': 400, 'headers': headers, 'body': 'No ROM'}
            
            game_name = rom_key.split('/')[-1]
            _, ext = os.path.splitext(game_name)
            core_name = CORE_MAP.get(ext.lower(), 'nestopia')

            # Script
            script_path = os.path.join(os.path.dirname(__file__), 'install.sh')
            with open(script_path, 'r') as file: script_content = file.read()
            
            script_content = script_content.replace('{{BUCKET}}', os.environ['ROMS_BUCKET'])
            script_content = script_content.replace('{{KEY}}', rom_key)
            script_content = script_content.replace('{{CORE}}', core_name)
            
            mime_userdata = (
                'Content-Type: multipart/mixed; boundary="//"\n'
                'MIME-Version: 1.0\n\n'
                '--//\n'
                'Content-Type: text/x-shellscript; charset="us-ascii"\n'
                'MIME-Version: 1.0\n'
                'Content-Transfer-Encoding: 7bit\n'
                'Content-Disposition: attachment; filename="userdata.txt"\n\n'
                f'{script_content}\n'
                '--//--'
            )
            encoded_ud = base64.b64encode(mime_userdata.encode('utf-8')).decode('ascii')

            # Retry AZ
            subnets = os.environ['SUBNET_IDS'].split(',')
            run_instances = None
            last_error = None

            for subnet_id in subnets:
                try:
                    run_instances = ec2.run_instances(
                        ImageId=AMI_ID,
                        InstanceType=INSTANCE_TYPE,
                        MinCount=1, MaxCount=1,
                        KeyName=SSH_KEY_NAME,
                        UserData=encoded_ud,
                        NetworkInterfaces=[{
                            'DeviceIndex': 0,
                            'SubnetId': subnet_id,
                            'Groups': [os.environ['SG_ID']],
                            'AssociatePublicIpAddress': True
                        }],
                        IamInstanceProfile={'Name': os.environ['PROFILE_NAME']},
                        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': f'Retro-{game_name}'}]}],
                        InstanceMarketOptions={'MarketType': 'spot', 'SpotOptions': {'SpotInstanceType': 'one-time'}}
                    )
                    break 
                except ClientError as e:
                    last_error = str(e)
                    continue

            if not run_instances:
                return { 'statusCode': 500, 'headers': headers, 'body': json.dumps({'error': f"Echec: {last_error}"}) }

            instance_id = run_instances['Instances'][0]['InstanceId']
            
            # Wait IP
            public_ip = None
            for _ in range(10):
                try:
                    desc = ec2.describe_instances(InstanceIds=[instance_id])
                    public_ip = desc['Reservations'][0]['Instances'][0].get('PublicIpAddress')
                    if public_ip: break
                except: pass
                time.sleep(1)
            
            # CONSTRUCTION DE L'URL SECURISEE (SSLIP.IO)
            # Ex: 52.1.2.3 devient 52-1-2-3.sslip.io
            # Caddy sur l'instance va generer le certificat pour ce domaine automatiquement
            if public_ip:
                dashed_ip = public_ip.replace('.', '-')
                secure_domain = f"{dashed_ip}.sslip.io"
                return { 'statusCode': 200, 'headers': headers, 'body': json.dumps({ 'ip': public_ip, 'url': f"https://{secure_domain}", 'id': instance_id }) }
            
            return { 'statusCode': 200, 'headers': headers, 'body': json.dumps({ 'ip': 'WAITING', 'id': instance_id }) }

        except Exception as e:
            print(f"ERROR: {e}")
            return { 'statusCode': 500, 'headers': headers, 'body': json.dumps({'error': str(e)}) }

    return { 'statusCode': 400, 'headers': headers, 'body': 'Bad Request' }