# -*- coding: utf-8 -*-
"""The parser mediator."""

import collections
import datetime
import time

import pytz

from plaso.containers import artifacts
from plaso.containers import warnings
from plaso.engine import path_helper
from plaso.engine import profilers
from plaso.helpers import language_tags
from plaso.helpers.windows import languages


class ParserMediator(object):
  """Parser mediator.

  Attributes:
    collection_filters_helper (CollectionFiltersHelper): collection filters
        helper.
    last_activity_timestamp (int): timestamp received that indicates the last
        time activity was observed. The last activity timestamp is updated
        when the mediator produces an attribute container, such as an event
        source. This timestamp is used by the multi processing worker process
        to indicate the last time the worker was known to be active. This
        information is then used by the foreman to detect workers that are
        not responding (stalled).
    parsers_counter (collections.Counter): number of events per parser or
        parser plugin.
  """

  _DEFAULT_LANGUAGE_TAG = 'en-US'

  # LCID 0x0409 is en-US.
  _DEFAULT_LCID = 0x0409

  _DEFAULT_TIME_ZONE = pytz.UTC

  _INT64_MIN = -1 << 63
  _INT64_MAX = (1 << 63) - 1

  def __init__(
      self, knowledge_base, collection_filters_helper=None,
      resolver_context=None):
    """Initializes a parser mediator.

    Args:
      knowledge_base (KnowledgeBase): contains information from the source
          data needed for parsing.
      collection_filters_helper (Optional[CollectionFiltersHelper]): collection
          filters helper.
      resolver_context (Optional[dfvfs.Context]): resolver context.
    """
    super(ParserMediator, self).__init__()
    self._abort = False
    self._cached_parser_chain = None
    self._cpu_time_profiler = None
    self._event_data_stream_identifier = None
    self._extract_winevt_resources = True
    self._file_entry = None
    self._knowledge_base = knowledge_base
    self._language_tag = self._DEFAULT_LANGUAGE_TAG
    self._last_event_data_hash = None
    self._last_event_data_identifier = None
    self._lcid = self._DEFAULT_LCID
    self._memory_profiler = None
    self._number_of_event_data = 0
    self._number_of_event_sources = 0
    self._number_of_extraction_warnings = 0
    self._number_of_recovery_warnings = 0
    self._parser_chain_components = []
    self._preferred_codepage = None
    self._process_information = None
    self._resolver_context = resolver_context
    self._storage_writer = None
    self._temporary_directory = None
    self._text_prepend = None
    self._time_zone = None
    self._windows_event_log_providers_per_path = None

    self.collection_filters_helper = collection_filters_helper
    self.last_activity_timestamp = 0.0
    self.parsers_counter = collections.Counter()

  @property
  def abort(self):
    """bool: True if parsing should be aborted."""
    return self._abort

  @property
  def codepage(self):
    """str: preferred codepage in lower case."""
    if not self._preferred_codepage:
      self._preferred_codepage = self._knowledge_base.codepage.lower()
    return self._preferred_codepage

  @property
  def extract_winevt_resources(self):
    """bool: extract Windows EventLog resources."""
    return self._extract_winevt_resources

  @property
  def language(self):
    """str: language tag in lower case."""
    if not self._language_tag:
      language_tag = (
          self._knowledge_base.language.lower() or self._DEFAULT_LANGUAGE_TAG)
      self._language_tag = language_tag.lower()

    return self._language_tag

  @property
  def number_of_produced_event_data(self):
    """int: number of produced event data."""
    return self._number_of_event_data

  @property
  def number_of_produced_event_sources(self):
    """int: number of produced event sources."""
    return self._number_of_event_sources

  @property
  def number_of_produced_extraction_warnings(self):
    """int: number of produced extraction warnings."""
    return self._number_of_extraction_warnings

  @property
  def resolver_context(self):
    """dfvfs.Context: resolver context."""
    return self._resolver_context

  @property
  def temporary_directory(self):
    """str: path of the directory for temporary files."""
    return self._temporary_directory

  @property
  def timezone(self):
    """datetime.tzinfo: timezone."""
    if not self._time_zone:
      self._time_zone = self._knowledge_base.timezone or self._DEFAULT_TIME_ZONE

    return self._time_zone

  def AddYearLessLogHelper(self, year_less_log_helper):
    """Adds a year-less log helper.

    Args:
      year_less_log_helper (YearLessLogHelper): year-less log helper.
    """
    if self._event_data_stream_identifier:
      year_less_log_helper.SetEventDataStreamIdentifier(
          self._event_data_stream_identifier)

    self._storage_writer.AddAttributeContainer(year_less_log_helper)

  def AddWindowsEventLogMessageFile(self, message_file):
    """Adds a Windows EventLog message file.

    Args:
      message_file (WindowsEventLogMessageFileArtifact): Windows EventLog
          message file.
    """
    self._storage_writer.AddAttributeContainer(message_file)

  def AddWindowsEventLogMessageString(self, message_string):
    """Adds a Windows EventLog message string.

    Args:
      message_string (WindowsEventLogMessageStringArtifact): Windows EventLog
          message string.
    """
    self._storage_writer.AddAttributeContainer(message_string)

  def AddWindowsWevtTemplateEvent(self, event_definition):
    """Adds a Windows WEVT_TEMPLATE event definition.

    Args:
      event_definition (WindowsWevtTemplateEvent): Windows WEVT_TEMPLATE event
          definition.
    """
    self._storage_writer.AddAttributeContainer(event_definition)

  def AppendToParserChain(self, name):
    """Adds a parser or parser plugin to the parser chain.

    Args:
      name (str): name of a parser or parser plugin.
    """
    self._cached_parser_chain = None
    self._parser_chain_components.append(name)

  def ClearParserChain(self):
    """Clears the parser chain."""
    self._cached_parser_chain = None
    self._parser_chain_components = []

  def ExpandWindowsPath(self, path):
    """Expands a Windows path containing environment variables.

    Args:
      path (str): Windows path with environment variables.

    Returns:
      str: expanded Windows path.
    """
    environment_variables = self._knowledge_base.GetEnvironmentVariables()
    return path_helper.PathHelper.ExpandWindowsPath(path, environment_variables)

  def GetCurrentYear(self):
    """Retrieves current year.

    Returns:
      int: the current year.
    """
    datetime_object = datetime.datetime.now()
    return datetime_object.year

  def GetDisplayName(self, file_entry=None):
    """Retrieves the display name for a file entry.

    Args:
      file_entry (Optional[dfvfs.FileEntry]): file entry object, where None
          will return the display name of self._file_entry.

    Returns:
      str: human readable string that describes the path to the file entry.

    Raises:
      ValueError: if the file entry is missing.
    """
    if file_entry is None:
      file_entry = self._file_entry

    if file_entry is None:
      raise ValueError('Missing file entry')

    path_spec = getattr(file_entry, 'path_spec', None)

    relative_path = path_helper.PathHelper.GetRelativePathForPathSpec(path_spec)
    if not relative_path:
      return file_entry.name

    return path_helper.PathHelper.GetDisplayNameForPathSpec(
        path_spec, text_prepend=self._text_prepend)

  def GetDisplayNameForPathSpec(self, path_spec):
    """Retrieves the display name for a path specification.

    Args:
      path_spec (dfvfs.PathSpec): path specification.

    Returns:
      str: human readable version of the path specification.
    """
    return path_helper.PathHelper.GetDisplayNameForPathSpec(
        path_spec, text_prepend=self._text_prepend)

  def GetFileEntry(self):
    """Retrieves the active file entry.

    Returns:
      dfvfs.FileEntry: file entry or None if not available.
    """
    return self._file_entry

  def GetFilename(self):
    """Retrieves the name of the active file entry.

    Returns:
      str: name of the active file entry or None.
    """
    if not self._file_entry:
      return None

    data_stream = getattr(self._file_entry.path_spec, 'data_stream', None)
    if data_stream:
      return '{0:s}:{1:s}'.format(self._file_entry.name, data_stream)

    return self._file_entry.name

  def GetParserChain(self):
    """Retrieves the current parser chain.

    Returns:
      str: parser chain.
    """
    if not self._cached_parser_chain:
      self._cached_parser_chain = '/'.join(self._parser_chain_components)
    return self._cached_parser_chain

  def GetRelativePath(self):
    """Retrieves the relative path of the current file entry.

    Returns:
      str: relative path of the current file entry or None if no current
          file entry.
    """
    if self._file_entry is None:
      return None

    return path_helper.PathHelper.GetRelativePathForPathSpec(
        self._file_entry.path_spec)

  def GetRelativePathForPathSpec(self, path_spec):
    """Retrieves the relative path for a path specification.

    Args:
      path_spec (dfvfs.PathSpec): path specification.

    Returns:
      str: relative path of the path specification.
    """
    return path_helper.PathHelper.GetRelativePathForPathSpec(path_spec)

  def GetWindowsEventLogMessageFile(self):
    """Retrieves the Windows EventLog message file for a specific path.

    Returns:
      WindowsEventLogMessageFileArtifact: Windows EventLog message file or None
          if no current file entry or no Windows EventLog message file was
          found.
    """
    if self._windows_event_log_providers_per_path is None:
      self._windows_event_log_providers_per_path = {}
      environment_variables = self._knowledge_base.GetEnvironmentVariables()

      for provider in self._knowledge_base.GetWindowsEventLogProviders():
        for windows_path in provider.event_message_files or []:
          path, filename = path_helper.PathHelper.GetWindowsSystemPath(
              windows_path, environment_variables)
          path = path.lower()
          filename = filename.lower()

          # Use the path prefix as the key to handle language specific EventLog
          # message files.
          if path not in self._windows_event_log_providers_per_path:
            self._windows_event_log_providers_per_path[path] = {}

          # Note that multiple providers can share EventLog message files.
          self._windows_event_log_providers_per_path[path][filename] = provider

    message_file = None
    if self._file_entry:
      relative_path = path_helper.PathHelper.GetRelativePathForPathSpec(
          self._file_entry.path_spec)
      lookup_path = relative_path.lower()

      path_segment_separator = path_helper.PathHelper.GetPathSegmentSeparator(
          self._file_entry.path_spec)

      lookup_path, _, lookup_filename = lookup_path.rpartition(
          path_segment_separator)

      # Language specific EventLog message file paths contain a language tag
      # such as "en-US".
      base_lookup_path, _, last_path_segment = lookup_path.rpartition(
          path_segment_separator)
      if language_tags.LanguageTagHelper.IsLanguageTag(last_path_segment):
        lookup_path = base_lookup_path

      providers_per_filename = self._windows_event_log_providers_per_path.get(
          lookup_path, {})

      for filename, provider in providers_per_filename.items():
        mui_filename = '{0:s}.mui'.format(filename)
        if lookup_filename in (filename, mui_filename):
          windows_path = '\\'.join([lookup_path, filename])
          message_file = artifacts.WindowsEventLogMessageFileArtifact(
              path=relative_path, windows_path=windows_path)
          break

    return message_file

  def PopFromParserChain(self):
    """Removes the last added parser or parser plugin from the parser chain."""
    self._cached_parser_chain = None
    self._parser_chain_components.pop()

  def ProduceEventData(self, event_data):
    """Produces event data.

    Args:
      event_data (EventData): event data.

    Raises:
      RuntimeError: when storage writer is not set.
    """
    if not self._storage_writer:
      raise RuntimeError('Storage writer not set.')

    # TODO: rename this to event_data.parser_chain or equivalent.
    if not event_data.parser:
      event_data.parser = self.GetParserChain()

    if self._event_data_stream_identifier:
      event_data.SetEventDataStreamIdentifier(
          self._event_data_stream_identifier)

    self._storage_writer.AddAttributeContainer(event_data)
    self._number_of_event_data += 1

    self.last_activity_timestamp = time.time()

  def ProduceEventDataStream(self, event_data_stream):
    """Produces an event data stream.

    Args:
      event_data_stream (EventDataStream): an event data stream or None if no
          event data stream is needed.

    Raises:
      RuntimeError: when storage writer is not set.
    """
    if not self._storage_writer:
      raise RuntimeError('Storage writer not set.')

    if not event_data_stream:
      self._event_data_stream_identifier = None
    else:
      if not event_data_stream.path_spec:
        event_data_stream.path_spec = getattr(
            self._file_entry, 'path_spec', None)

      self._storage_writer.AddAttributeContainer(event_data_stream)

      self._event_data_stream_identifier = event_data_stream.GetIdentifier()

    self.last_activity_timestamp = time.time()

  def ProduceEventSource(self, event_source):
    """Produces an event source.

    Args:
      event_source (EventSource): an event source.

    Raises:
      RuntimeError: when storage writer is not set.
    """
    if not self._storage_writer:
      raise RuntimeError('Storage writer not set.')

    self._storage_writer.AddAttributeContainer(event_source)
    self._number_of_event_sources += 1

    self.last_activity_timestamp = time.time()

  def ProduceExtractionWarning(self, message, path_spec=None):
    """Produces an extraction warning.

    Args:
      message (str): message of the warning.
      path_spec (Optional[dfvfs.PathSpec]): path specification, where None
          will use the path specification of current file entry set in
          the mediator.

    Raises:
      RuntimeError: when storage writer is not set.
    """
    if not self._storage_writer:
      raise RuntimeError('Storage writer not set.')

    if not path_spec and self._file_entry:
      path_spec = self._file_entry.path_spec

    parser_chain = self.GetParserChain()
    warning = warnings.ExtractionWarning(
        message=message, parser_chain=parser_chain, path_spec=path_spec)
    self._storage_writer.AddAttributeContainer(warning)
    self._number_of_extraction_warnings += 1

    self.last_activity_timestamp = time.time()

  def ProduceRecoveryWarning(self, message, path_spec=None):
    """Produces a recovery warning.

    Args:
      message (str): message of the warning.
      path_spec (Optional[dfvfs.PathSpec]): path specification, where None
          will use the path specification of current file entry set in
          the mediator.

    Raises:
      RuntimeError: when storage writer is not set.
    """
    if not self._storage_writer:
      raise RuntimeError('Storage writer not set.')

    if not path_spec and self._file_entry:
      path_spec = self._file_entry.path_spec

    parser_chain = self.GetParserChain()
    warning = warnings.RecoveryWarning(
        message=message, parser_chain=parser_chain, path_spec=path_spec)
    self._storage_writer.AddAttributeContainer(warning)
    self._number_of_recovery_warnings += 1

    self.last_activity_timestamp = time.time()

  def ResetFileEntry(self):
    """Resets the active file entry."""
    self._file_entry = None

  def SampleMemoryUsage(self, parser_name):
    """Takes a sample of the memory usage for profiling.

    Args:
      parser_name (str): name of the parser.
    """
    if self._memory_profiler:
      used_memory = self._process_information.GetUsedMemory() or 0
      self._memory_profiler.Sample(parser_name, used_memory)

  def SampleStartTiming(self, parser_name):
    """Starts timing a CPU time sample for profiling.

    Args:
      parser_name (str): name of the parser.
    """
    if self._cpu_time_profiler:
      self._cpu_time_profiler.StartTiming(parser_name)

  def SampleStopTiming(self, parser_name):
    """Stops timing a CPU time sample for profiling.

    Args:
      parser_name (str): name of the parser.
    """
    if self._cpu_time_profiler:
      self._cpu_time_profiler.StopTiming(parser_name)

  def SetExtractWinEvtResources(self, extract_winevt_resources):
    """Sets value to indicate if Windows EventLog resources should be extracted.

    Args:
      extract_winevt_resources (bool): True if Windows EventLog resources
          should be extracted.
    """
    self._extract_winevt_resources = extract_winevt_resources

  def SetFileEntry(self, file_entry):
    """Sets the active file entry.

    Args:
      file_entry (dfvfs.FileEntry): file entry.
    """
    self._file_entry = file_entry
    self._event_data_stream_identifier = None

  def SetPreferredCodepage(self, codepage):
    """Sets the preferred codepage.

    Args:
      codepage (str): codepage.
    """
    self._preferred_codepage = codepage

  def SetPreferredLanguage(self, language_tag):
    """Sets the preferred language.

    Args:
      language_tag (str): language tag such as "en-US" for US English or
          "is-IS" for Icelandic or None if the language determined by
          preprocessing or the default should be used.

    Raises:
      ValueError: if the language tag is not a string type or no LCID can
          be determined that corresponds with the language tag.
    """
    lcid = None
    if language_tag is not None:
      if not isinstance(language_tag, str):
        raise ValueError('Language tag: {0!s} is not a string.'.format(
            language_tag))

      lcid = languages.WindowsLanguageHelper.GetLCIDForLanguageTag(language_tag)
      if not lcid:
        raise ValueError('No LCID found for language tag: {0:s}.'.format(
            language_tag))

    self._language_tag = language_tag
    self._lcid = lcid

  def SetPreferredTimeZone(self, time_zone_string):
    """Sets the preferred time zone for zone-less date and time values.

    Args:
      time_zone_string (str): time zone such as "Europe/Amsterdam" or None if
          the time zone determined by preprocessing or the default should be
          used.

    Raises:
      ValueError: if the time zone is not supported.
    """
    time_zone = None
    if time_zone_string:
      try:
        time_zone = pytz.timezone(time_zone_string)
      except pytz.UnknownTimeZoneError:
        raise ValueError('Unsupported time zone: {0!s}'.format(
            time_zone_string))

    self._time_zone = time_zone

  def SetStorageWriter(self, storage_writer):
    """Sets the storage writer.

    Args:
      storage_writer (StorageWriter): storage writer.
    """
    self._storage_writer = storage_writer

    # Reset the last event data information. Each storage file should
    # contain event data for their events.
    self._last_event_data_hash = None

  def SetTemporaryDirectory(self, temporary_directory):
    """Sets the directory to store temporary files.

    Args:
      temporary_directory (str): path of the directory to store temporary files.
    """
    self._temporary_directory = temporary_directory

  def SetTextPrepend(self, text_prepend):
    """Sets the text to prepend to the display name.

    Args:
      text_prepend (str): text to prepend to the display name or None if no
          text should be prepended.
    """
    self._text_prepend = text_prepend

  def SignalAbort(self):
    """Signals the parsers to abort."""
    self._abort = True

  def StartProfiling(self, configuration, identifier, process_information):
    """Starts profiling.

    Args:
      configuration (ProfilingConfiguration): profiling configuration.
      identifier (str): identifier of the profiling session used to create
          the sample filename.
      process_information (ProcessInfo): process information.
    """
    if not configuration:
      return

    if configuration.HaveProfileParsers():
      identifier = '{0:s}-parsers'.format(identifier)

      self._cpu_time_profiler = profilers.CPUTimeProfiler(
          identifier, configuration)
      self._cpu_time_profiler.Start()

      self._memory_profiler = profilers.MemoryProfiler(
          identifier, configuration)
      self._memory_profiler.Start()

    self._process_information = process_information

  def StopProfiling(self):
    """Stops profiling."""
    if self._cpu_time_profiler:
      self._cpu_time_profiler.Stop()
      self._cpu_time_profiler = None

    if self._memory_profiler:
      self._memory_profiler.Stop()
      self._memory_profiler = None

    self._process_information = None
