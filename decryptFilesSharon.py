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
from database.profiling_models import DecryptionKeyError, EncryptionErrorMetadata, LineEncryptionError, UploadTracking

def main():
    files = UploadTracking.objects.filter(file_path__contains="jfcztjpm/gps", timestamp__contains="2018-07-07")
    study_id = "trZYX7jrpn52YFdkqkmlfJqj"
    for each in files:
            ftp_as_object = each
            ftp = ftp_as_object.as_dict()
            print(ftp)
            data_type = 'gps'
            ret = {'ftp': ftp,
               "data_type": data_type,
               'exception': None,
               "file_contents": "",
               "traceback": None}
            print(study_id + "/" + ftp['file_path'] + "\ngetting data...")
            ret['file_contents'] = s3_retrieve(study_id + "/" + ftp['file_path'], study_id, raw_path=True)
            print("finished getting data")
            print(ret['file_contents'])

main()