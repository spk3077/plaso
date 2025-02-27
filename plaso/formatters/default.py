# -*- coding: utf-8 -*-
"""The default event formatter."""

from dfdatetime import interface as dfdatetime_interface

from plaso.containers import interface as containers_interface
from plaso.formatters import interface
from plaso.lib import definitions


class DefaultEventFormatter(interface.BasicEventFormatter):
  """Formatter for events that do not have any defined formatter."""

  DATA_TYPE = 'event'
  FORMAT_STRING = '<WARNING DEFAULT FORMATTER> Attributes: {attribute_values}'
  FORMAT_STRING_SHORT = '<DEFAULT> {attribute_values}'

  def __init__(self):
    """Initializes a default event formatter."""
    super(DefaultEventFormatter, self).__init__(
        data_type=self.DATA_TYPE, format_string=self.FORMAT_STRING,
        format_string_short=self.FORMAT_STRING_SHORT)

  def _FormatMessage(self, format_string, event_values):
    """Determines the formatted message.

    Args:
      format_string (str): message format string.
      event_values (dict[str, object]): event values.

    Returns:
      str: formatted message.
    """
    text_pieces = []
    for name, value in event_values.items():
      # Ignore reserved variable names.
      if name in definitions.RESERVED_VARIABLE_NAMES:
        continue

      # Ignore attribute container identifier values.
      if isinstance(value, containers_interface.AttributeContainerIdentifier):
        continue

      # Ignore date and time values.
      if isinstance(value, dfdatetime_interface.DateTimeValues):
        continue

      text_pieces.append('{0:s}: {1!s}'.format(name, value))

    return super(DefaultEventFormatter, self)._FormatMessage(
        format_string, {'attribute_values': ' '.join(text_pieces)})
