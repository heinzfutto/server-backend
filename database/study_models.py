# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json

from django.db import models
from django.db.models import F, Func
from django.utils import timezone

from config.study_constants import (
    ABOUT_PAGE_TEXT, CONSENT_FORM_TEXT, DEFAULT_CONSENT_SECTIONS_JSON,
    SURVEY_SUBMIT_SUCCESS_TOAST_TEXT, AUDIO_SURVEY_SETTINGS
)
from libs.security import (
    compare_password, device_hash, generate_easy_alphanumeric_string, generate_hash_and_salt,
    generate_random_string, generate_user_hash_and_salt
)
from database.validators import (
    id_validator, standard_base_64_validator, url_safe_base_64_validator, LengthValidator
)

from database.base_models import AbstractModel, JSONTextField


class Study(AbstractModel):
    
    # When a Study object is created, a default DeviceSettings object is automatically
    # created alongside it. If the Study is created via the researcher interface (as it
    # usually is) the researcher is immediately shown the DeviceSettings to edit. The code
    # to create the DeviceSettings object is in database.signals.populate_study_device_settings.
    name = models.TextField(unique=True, help_text='Name of the study; can be of any length')
    encryption_key = models.CharField(max_length=32, validators=[LengthValidator(32)],
                                      help_text='Key used for encrypting the study data')
    object_id = models.CharField(max_length=24, unique=True, validators=[LengthValidator(24)],
                                 help_text='ID used for naming S3 files')

    is_test = models.BooleanField(default=True)

    @classmethod
    def create_with_object_id(cls, **kwargs):
        """
        Creates a new study with a populated object_id field
        """
        
        study = cls(object_id=cls.generate_objectid_string("object_id"), **kwargs)
        study.save()
        return study

    @classmethod
    def get_all_studies_by_name(cls):
        """
        Sort the un-deleted Studies a-z by name, ignoring case.
        """
        return (cls.objects
                .filter(deleted=False)
                .annotate(name_lower=Func(F('name'), function='LOWER'))
                .order_by('name_lower'))

    def get_surveys_for_study(self):
        survey_json_list = []
        for survey in self.surveys.filter(deleted=false):
            survey_dict = survey.as_native_python()
            # Make the dict look like the old Mongolia-style dict that the frontend is expecting
            survey_dict.pop('id')
            survey_dict.pop('deleted')
            survey_dict['_id'] = survey_dict.pop('object_id')
            survey_json_list.append(survey_dict)
        return survey_json_list

    def get_survey_ids_for_study(self, survey_type='tracking_survey'):
        return self.surveys.filter(survey_type=survey_type, deleted=False).values_list('id', flat=True)

    def get_survey_ids_and_object_ids_for_study(self, survey_type='tracking_survey'):
        return self.surveys.filter(survey_type=survey_type, deleted=False).values_list('id', 'object_id')

    def get_study_device_settings(self):
        return self.device_settings

    def get_researchers(self):
        return Researcher.objects.filter(studies=self)


class AbstractSurvey(AbstractModel):
    
    AUDIO_SURVEY = 'audio_survey'
    TRACKING_SURVEY = 'tracking_survey'
    DUMMY_SURVEY = 'dummy'
    IMAGE_SURVEY = 'image_survey'
    SURVEY_TYPE_CHOICES = (
        (AUDIO_SURVEY, AUDIO_SURVEY),
        (TRACKING_SURVEY, TRACKING_SURVEY),
        (DUMMY_SURVEY, DUMMY_SURVEY),
        (IMAGE_SURVEY, IMAGE_SURVEY)
    )
    
    content = JSONTextField(default='[]', help_text='JSON blob containing information about the survey questions.')
    survey_type = models.CharField(max_length=16, choices=SURVEY_TYPE_CHOICES,
                                   help_text='What type of survey this is.')
    settings = JSONTextField(default='{}', help_text='JSON blob containing settings for the survey.')
    timings = JSONTextField(default=json.dumps([[], [], [], [], [], [], []]),
                            help_text='JSON blob containing the times at which the survey is sent.')
    
    class Meta:
        abstract = True


class Survey(AbstractSurvey):
    """
    Surveys contain all information the app needs to display the survey correctly to a participant,
    and when it should push the notifications to take the survey.

    Surveys must have a 'survey_type', which is a string declaring the type of survey it
    contains, which the app uses to display the correct interface.

    Surveys contain 'content', which is a JSON blob that is unpacked on the app and displayed
    to the participant in the form indicated by the survey_type.

    Timings schema: a survey must indicate the day of week and time of day on which to trigger;
    by default it contains no values. The timings schema mimics the Java.util.Calendar.DayOfWeek
    specification: it is zero-indexed with day 0 as Sunday. 'timings' is a list of 7 lists, each
    inner list containing any number of times of the day. Times of day are integer values
    indicating the number of seconds past midnight.
    """
    
    # Every time that a Survey object is saved (except upon creation), a SurveyArchive object
    # is created. The SurveyArchive object contains all of the AbstractSurvey fields that the
    # Survey object did *before* it was saved, as well as a pair of timestamps marking during
    # what time period the SurveyArchive applies. The code that creates SurveyArchive objects
    # is found in database.signals.create_survey_archive.
    last_modified = models.DateTimeField(auto_now=True)
    
    # This is required for file name and path generation
    object_id = models.CharField(max_length=24, unique=True, validators=[LengthValidator(24)])
    
    study = models.ForeignKey('Study', on_delete=models.PROTECT, related_name='surveys')

    @classmethod
    def create_with_object_id(cls, **kwargs):
        object_id = cls.generate_objectid_string("object_id")
        survey = cls.objects.create(object_id=object_id, **kwargs)
        return survey

    @classmethod
    def create_with_settings(cls, survey_type, **kwargs):
        """
        Create a new Survey with the provided survey type and attached to the given Study,
        as well as any other given keyword arguments. If the Survey is audio and no other
        settings are given, give it the default audio survey settings.
        """

        if survey_type == cls.AUDIO_SURVEY and 'settings' not in kwargs:
            kwargs['settings'] = json.dumps(AUDIO_SURVEY_SETTINGS)

        survey = cls.create_with_object_id(survey_type=survey_type, **kwargs)
        return survey


class SurveyArchive(AbstractSurvey):
    
    archive_start = models.DateTimeField()
    archive_end = models.DateTimeField(default=timezone.now)
    
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='archives')
    study = models.ForeignKey('Study', on_delete=models.PROTECT, related_name='surveys_archive')


class AbstractPasswordUser(AbstractModel):
    """
    The AbstractPasswordUser (APU) model is used to enable basic password functionality for human
    users of the database, whatever variety of user they may be.

    APU descendants have passwords hashed once with sha256 and many times (as defined in
    settings.py) with PBKDF2, and salted using a cryptographically secure random number
    generator. The sha256 check duplicates the storage of the password on the mobile device, so
    that the APU's password is never stored in a reversible manner.
    """

    password = models.CharField(max_length=44, validators=[url_safe_base_64_validator],
                                help_text='A hash of the user\'s password')
    salt = models.CharField(max_length=24, validators=[url_safe_base_64_validator])

    def generate_hash_and_salt(self, password):
        """
        Generate a password hash and random salt from a given password. This is different
        for different types of APUs, depending on whether they use mobile or web.
        """
        raise NotImplementedError

    def set_password(self, password):
        """
        Sets the instance's password hash to match the hash of the provided string.
        """
        password_hash, salt = self.generate_hash_and_salt(password)
        self.password = password_hash
        self.salt = salt
        self.save()

    def reset_password(self):
        """
        Resets the patient's password to match an sha256 hash of a randomly generated string.
        """
        password = generate_easy_alphanumeric_string()
        self.set_password(password)
        return password

    def validate_password(self, compare_me):
        """
        Checks if the input matches the instance's password hash.
        """
        return compare_password(compare_me, self.salt, self.password)

    class Meta:
        abstract = True


class Participant(AbstractPasswordUser):
    """
    The Participant database object contains the password hashes and unique usernames of any
    participants in the study, as well as information about the device the participant is using.
    A Participant uses mobile, so their passwords are hashed accordingly.
    """
    
    IOS_API = "IOS"
    ANDROID_API = "ANDROID"
    NULL_OS = ''
    
    OS_TYPE_CHOICES = (
        (IOS_API, IOS_API),
        (ANDROID_API, ANDROID_API),
        (NULL_OS, NULL_OS),
    )

    patient_id = models.CharField(max_length=8, unique=True, validators=[id_validator],
                                  help_text='Eight-character unique ID with characters chosen from 1-9 and a-z')

    device_id = models.CharField(max_length=256, blank=True,
                                 help_text='The ID of the device that the participant is using for the study, if any.')
    os_type = models.CharField(max_length=16, choices=OS_TYPE_CHOICES, blank=True,
                               help_text='The type of device the participant is using, if any.')

    study = models.ForeignKey('Study', on_delete=models.PROTECT, related_name='participants', null=False)

    @classmethod
    def create_with_password(cls, **kwargs):
        """
        Creates a new participant with randomly generated patient_id and password.
        """
	# Runshan: change patient id rule
	existing_count = cls.objects.count()
	patient_id = 'SG' +str(100 + existing_count).zfill(5)
        # Ensure that a unique patient_id is generated. If it is not after
        # twenty tries, raise an error.

        # patient_id = generate_easy_alphanumeric_string()
        # for _ in xrange(20):
            # if not cls.objects.filter(patient_id=patient_id).exists():
                # If patient_id does not exist in the database already
                # break
            # patient_id = generate_easy_alphanumeric_string()
        # else:
            #raise RuntimeError('Could not generate unique Patient ID for new Participant.')

        # Create a Participant, and generate for them a password
        participant = cls(patient_id=patient_id, **kwargs)
        password = participant.reset_password()  # this saves participant

        return patient_id, password

    def generate_hash_and_salt(self, password):
        return generate_user_hash_and_salt(password)

    def debug_validate_password(self, compare_me):
        """
        Checks if the input matches the instance's password hash, but does
        the hashing for you for use on the command line. This is necessary
        for manually checking that setting and validating passwords work.
        """
        compare_me = device_hash(compare_me)
        return compare_password(compare_me, self.salt, self.password)

    def set_device(self, device_id):
        self.device_id = device_id
        self.save()

    def set_os_type(self, os_type):
        self.os_type = os_type
        self.save()

    def clear_device(self):
        self.device_id = ''
        self.save()


class Researcher(AbstractPasswordUser):
    """
    The Researcher database object contains the password hashes and unique usernames of any
    researchers, as well as their data access credentials. A Researcher can be attached to
    multiple Studies, and a Researcher may also be an admin who has extra permissions.
    A Researcher uses web, so their passwords are hashed accordingly.
    """

    username = models.CharField(max_length=32, unique=True, help_text='User-chosen username, stored in plain text')
    admin = models.BooleanField(default=False, help_text='Whether the researcher is also an admin')

    access_key_id = models.CharField(max_length=64, validators=[standard_base_64_validator], unique=True, null=True, blank=True)
    access_key_secret = models.CharField(max_length=44, validators=[url_safe_base_64_validator], blank=True)
    access_key_secret_salt = models.CharField(max_length=24, validators=[url_safe_base_64_validator], blank=True)

    studies = models.ManyToManyField('Study', related_name='researchers')

    @classmethod
    def create_with_password(cls, username, password, **kwargs):
        """
        Creates a new Researcher with provided username and password. They will initially
        not be associated with any Study.
        """

        researcher = cls(username=username, **kwargs)
        researcher.set_password(password)
        # todo add check to see if access credentials are in kwargs
        researcher.reset_access_credentials()
        return researcher

    @classmethod
    def create_without_password(cls, username):
        """
        Create a new Researcher with provided username and no password
        """

        r = cls(username=username, password='fakepassword', salt='cab', admin=False)
        r.reset_access_credentials()
        return r

    @classmethod
    def check_password(cls, username, compare_me):
        """
        Checks if the provided password matches the hash of the provided Researcher's password.
        """
        if not Researcher.objects.filter(username=username).exists():
            return False
        researcher = Researcher.objects.get(username=username)
        return researcher.validate_password(compare_me)

    @classmethod
    def get_all_researchers_by_username(cls):
        """
        Sort the un-deleted Researchers a-z by username, ignoring case.
        """
        return (cls.objects
                .filter(deleted=False)
                .annotate(username_lower=Func(F('username'), function='LOWER'))
                .order_by('username_lower'))

    def generate_hash_and_salt(self, password):
        return generate_hash_and_salt(password)

    def elevate_to_admin(self):
        self.admin = True
        self.save()

    def validate_access_credentials(self, proposed_secret_key):
        """ Returns True/False if the provided secret key is correct for this user."""
        return compare_password(
            proposed_secret_key,
            self.access_key_secret_salt,
            self.access_key_secret
        )

    def reset_access_credentials(self):
        access_key = generate_random_string()[:64]
        secret_key = generate_random_string()[:64]
        secret_hash, secret_salt = generate_hash_and_salt(secret_key)
        self.access_key_id = access_key
        self.access_key_secret = secret_hash
        self.access_key_secret_salt = secret_salt
        self.save()
        return access_key, secret_key


class DeviceSettings(AbstractModel):
    """
    The DeviceSettings database contains the structure that defines
    settings pushed to devices of users in of a study.
    """

    # Whether various device options are turned on
    accelerometer = models.BooleanField(default=True)
    gps = models.BooleanField(default=True)
    calls = models.BooleanField(default=True)
    texts = models.BooleanField(default=True)
    wifi = models.BooleanField(default=True)
    bluetooth = models.BooleanField(default=False)
    power_state = models.BooleanField(default=True)

    # Whether iOS-specific data streams are turned on
    proximity = models.BooleanField(default=False)
    gyro = models.BooleanField(default=False)
    magnetometer = models.BooleanField(default=False)
    devicemotion = models.BooleanField(default=False)
    reachability = models.BooleanField(default=True)

    # Upload over cellular data or only over WiFi (WiFi-only is default)
    allow_upload_over_cellular_data = models.BooleanField(default=False)

    # Timer variables
    accelerometer_off_duration_seconds = models.PositiveIntegerField(default=10)
    accelerometer_on_duration_seconds = models.PositiveIntegerField(default=10)
    bluetooth_on_duration_seconds = models.PositiveIntegerField(default=60)
    bluetooth_total_duration_seconds = models.PositiveIntegerField(default=300)
    bluetooth_global_offset_seconds = models.PositiveIntegerField(default=0)
    check_for_new_surveys_frequency_seconds = models.PositiveIntegerField(default=3600 * 6)
    create_new_data_files_frequency_seconds = models.PositiveIntegerField(default=15 * 60)
    gps_off_duration_seconds = models.PositiveIntegerField(default=600)
    gps_on_duration_seconds = models.PositiveIntegerField(default=60)
    seconds_before_auto_logout = models.PositiveIntegerField(default=600)
    upload_data_files_frequency_seconds = models.PositiveIntegerField(default=3600)
    voice_recording_max_time_length_seconds = models.PositiveIntegerField(default=240)
    wifi_log_frequency_seconds = models.PositiveIntegerField(default=300)

    # iOS-specific timer variables
    gyro_off_duration_seconds = models.PositiveIntegerField(default=600)
    gyro_on_duration_seconds = models.PositiveIntegerField(default=60)
    magnetometer_off_duration_seconds = models.PositiveIntegerField(default=600)
    magnetometer_on_duration_seconds = models.PositiveIntegerField(default=60)
    devicemotion_off_duration_seconds = models.PositiveIntegerField(default=600)
    devicemotion_on_duration_seconds = models.PositiveIntegerField(default=60)

    # Text strings
    about_page_text = models.TextField(default=ABOUT_PAGE_TEXT)
    call_clinician_button_text = models.TextField(default='Call My Clinician')
    consent_form_text = models.TextField(default=CONSENT_FORM_TEXT)
    survey_submit_success_toast_text = models.TextField(default=SURVEY_SUBMIT_SUCCESS_TOAST_TEXT)

    # Consent sections
    consent_sections = JSONTextField(default=DEFAULT_CONSENT_SECTIONS_JSON)

    study = models.OneToOneField('Study', on_delete=models.PROTECT, related_name='device_settings')
