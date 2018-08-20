from config import load_django
import boto
from config.settings import S3_BUCKET, S3_ACCESS_CREDENTIALS_KEY,\
    S3_ACCESS_CREDENTIALS_USER, S3_REGION_NAME
from database.models import FileToProcess, Participant


def copy_and_insert(target_user_id, origin_user_id):
    print("Target:", target_user_id, "Origin:", origin_user_id)
    target_user = Participant.objects.get(patient_id=target_user_id)
    origin_user = Participant.objects.get(patient_id=origin_user_id)

    s3 = boto.connect_s3(S3_ACCESS_CREDENTIALS_USER, S3_ACCESS_CREDENTIALS_KEY)
    bucket = s3.get_bucket(S3_BUCKET)

    files_to_process = origin_user.files_to_process.all()
    for file in files_to_process:
        source_path = file.as_dict()['s3_file_path']
        destin_path = source_path.replace(origin_user_id, target_user_id)
        # copy files in the s3 bucket
        bucket.copy_key(destin_path, S3_BUCKET, source_path)
        # insert record in database
        FileToProcess.append_file_for_processing(destin_path,
                                                 target_user.study.object_id,
                                                 participant=target_user)
        print("finishe file:", destin_path)

if __name__ == '__main__':
    print("Start copy.")
    simulated_users = ['SG00'+str(x) for x in range(149, 175)]
    simulated_users.insert(0, 'SG00146')
    for user in simulated_users[:9]:
        copy_and_insert(user, "SG00144")
    for user in simulated_users[9:18]:
        copy_and_insert(user, 'SG00143')
    for user in simulated_users[18:]:
        copy_and_insert(user, 'n11fjdyt')
    print("Finish copy.")