from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_cloudfront as cloudfront, # <--- NOUVEAU
    aws_cloudfront_origins as origins # <--- NOUVEAU
)
from constructs import Construct

class RetroGamingCloudStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # 1. VPC
        vpc = ec2.Vpc(self, "RetroVPC",
            max_azs=3,
            subnet_configuration=[ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC)]
        )

        # 2. S3 BUCKETS
        roms_bucket = s3.Bucket(self, "RomsBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            cors=[s3.CorsRule(allowed_methods=[s3.HttpMethods.GET], allowed_origins=["*"])]
        )

        site_bucket = s3.Bucket(self, "SiteBucket",
            website_index_document="index.html",
            public_read_access=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ACLS
        )
        site_bucket.add_to_resource_policy(iam.PolicyStatement(
            actions=["s3:GetObject"], resources=[site_bucket.arn_for_objects("*")], principals=[iam.AnyPrincipal()]
        ))

        # --- NOUVEAU : CLOUDFRONT (HTTPS pour le site) ---
        distro = cloudfront.Distribution(self, "RetroDistro",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED # Pour dev, evite le cache
            )
        )

        # On deploie le site, puis on invalide le cache CloudFront pour voir les modifs de suite
        s3deploy.BucketDeployment(self, "DeployWebsite",
            sources=[s3deploy.Source.asset("./website")],
            destination_bucket=site_bucket,
            distribution=distro,
            distribution_paths=["/*"]
        )

        # 3. SECURITE
        ec2_role = iam.Role(self, "RetroInstanceRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"))
        roms_bucket.grant_read(ec2_role)
        instance_profile = iam.CfnInstanceProfile(self, "RetroProfile", roles=[ec2_role.role_name])

        # On garde les ports ouverts pour Caddy (80 pour le certificat, 443 pour le jeu)
        sg = ec2.SecurityGroup(self, "RetroSG_Secure", vpc=vpc, allow_all_outbound=True)
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "Allow Game HTTPS")
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "Allow Cert Validation")
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "Allow SSH")

        # 4. BACKEND LAMBDA
        subnet_ids = ",".join([s.subnet_id for s in vpc.public_subnets])

        backend_lambda = _lambda.Function(self, "RetroBackend",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="index.lambda_handler",
            code=_lambda.Code.from_asset("lambda_backend"),
            environment={
                "ROMS_BUCKET": roms_bucket.bucket_name,
                "SUBNET_IDS": subnet_ids,
                "SG_ID": sg.security_group_id,
                "PROFILE_NAME": instance_profile.ref
            },
            timeout=Duration.seconds(60),
            memory_size=256
        )

        roms_bucket.grant_read(backend_lambda)
        backend_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=["ec2:RunInstances", "ec2:DescribeInstances", "ec2:CreateTags", "iam:PassRole"],
            resources=["*"]
        ))

        # 5. API GATEWAY (Active CORS pour CloudFront)
        api = apigw.LambdaRestApi(self, "RetroApi", handler=backend_lambda,
            default_cors_preflight_options=apigw.CorsOptions(allow_origins=apigw.Cors.ALL_ORIGINS, allow_methods=apigw.Cors.ALL_METHODS))

        # Outputs : On donne l'URL CloudFront au lieu du S3 direct !
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "SecureSiteURL", value=f"https://{distro.distribution_domain_name}")