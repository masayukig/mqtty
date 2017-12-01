Mqtty
=====

Mqtty is a console-based interface client for MQTT protocol.

.. caution::
   This is still under heavily development phase.

How to use
----------

Source
~~~~~~

When installing from source, it is recommended (but not required) to
install mqtty in a virtualenv.  To set one up::

  $ virtualenv mqtty-env
  $ source mqtty-env/bin/activate


To install from a git checkout::

  $ pip install .

Mqtty uses a YAML based configuration file that it looks for at
``~/.mqtty.yaml``.  A sample configuration file is included. You can
find them in the examples/ directory of the `source repo
<https://github.com/masayukig/mqtty/tree/master/examples>`_.
So, you can use it like this::

  $ cp ./examples/mqtty.yaml ~/.mqtty.yaml
  $ vim ~/.mqtty.yaml
