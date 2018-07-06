from config import load_django

import json
from bson import ObjectId
from libs.s3 import s3_retrieve, s3_upload
from database.models import ChunkRegistry, FileProcessLock, FileToProcess, Participant, Survey
from config.constants import (ANDROID_LOG_FILE, UPLOAD_FILE_TYPE_MAPPING, API_TIME_FORMAT,
    IDENTIFIERS,
    WIFI, CALL_LOG, CHUNK_TIMESLICE_QUANTUM, FILE_PROCESS_PAGE_SIZE, SURVEY_TIMINGS, ACCELEROMETER,
    SURVEY_DATA_FILES, CONCURRENT_NETWORK_OPS, CHUNKS_FOLDER, CHUNKABLE_FILES,
    DATA_PROCESSING_NO_ERROR_STRING, IOS_LOG_FILE)
from database.study_models import DeviceSettings, Participant, Researcher, Study, Survey, SurveyArchive


def main():
    participants = Participant.objects.filter(files_to_process__isnull=False).distinct()
    for participant in participants:
        print(participant.as_native_python())
        print(participant.files_to_process.all()[0:250])
        print len(participant.files_to_process.all())
        for each in participant.files_to_process.all()[0:250]:
            ftp_as_object = each
            ftp = ftp_as_object.as_dict()
            print(ftp)
            data_type = 'gps'
            ret = {'ftp': ftp,
               "data_type": data_type,
               'exception': None,
               "file_contents": "",
               "traceback": None}
            print(ftp['s3_file_path'] + "\ngetting data...")
            ret['file_contents'] = s3_retrieve(ftp['s3_file_path'], ftp["study"].object_id, raw_path=True)
            print("finished getting data")
            print(ret['file_contents'])

main()