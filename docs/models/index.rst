.. _module-models:

Models
========

A **model** is defined as a Python class that defines a few methods and attributes to be used in the continual learning framework.
To be compatible with the *auto-detection* mechanism (the **get_model** function below), a model must:

* extend the base class :ref:`ContinualModel <module-models.utils.continual_model>`, which implements most of the required methods, leaving to the user the definition of the **observe** method (see in :ref:`training and testing`). In addition, the model must define the **NAME** and **COMPATIBILITY** attributes (see below).

* be defined in a file named **<model_name>.py** and placed in the **models** folder. 

The model-specific hyper-parameters of the model can be set in the **get_parser** static method (see in :ref:`Model parameters`). 

.. note::
    The name of the file will be used to identify the model. For example, if the model is defined in a file named **my_model.py**, the name of the model will be **my_model** and will be called with the command line option **--model my_model**.

.. important::
    Each file can contain **only one** model. If you want to define multiple models, you have to create multiple files.

Training and testing
--------------------

The **observe** method is the only method that **must** be implemented by the user. It is called at each training iteration and it is used to update the model parameters according to the current training batch. The method must have the following signature:

.. code-block:: python

    def observe(self, inputs: torch.Tensor, labels: torch.Tensor,
                not_aug_inputs: torch.Tensor, epoch: int = None) -> float:

        # Update the model parameters according to the current batch
        ...

        # Return the current loss value (as a float value)
        return loss.item()

The method receives as input the current training batch (i.e., **inputs** and **labels**), the original batch (i.e., **not_aug_inputs**) and (*optionally*) the current training epoch (i.e., **epoch**). The method must return the current loss value (as a float value).

Evaluation
~~~~~~~~~~

The **forward** method is used to evaluate the model on the test set. By default, it is implemented in the base class **ContinualModel** and just calls the **forward** method of the backbone model. However, it can be overridden to implement a different evaluation method. The method must have the following signature:

.. code-block:: python

    def forward(self, x: torch.Tensor) -> torch.Tensor:

        # Compute the output of the model
        ...

        # Return the output of the model
        return output

Attributes and utility methods
-------------------------------

The base class (:ref:`ContinualModel <module-models.utils.continual_model>`) includes the **NAME** and **COMPATIBILITY** attributes, which are used to identify the model and to check its compatibility with the chosen **setting** (see :ref:`module-datasets` for more details). The **NAME** attribute is a string that identifies the model, while the **COMPATIBILITY** attribute is a list of strings that identify the compatible settings. For example, :ref:`module-models.der` includes compatibility with ``['class-il', 'domain-il', 'task-il', 'general-continual']`` settings, and thus is compatible with all the datasets included in the framework. However, as it includes no compatibility with the ``'cssl'`` setting, it cannot take advantage of unlabeled samples (available if ``--label_perc_by_task`` or ``--label_perc_by_class`` is set to a value between ``0`` and ``1``).

Basic model class
~~~~~~~~~~~~~~~~~

The **ContinualModel** loads the backbone model (i.e., the model used to compute the output of the model, see :ref:`module-backbones`) during the initialization. By default, the backbone model is defined by the chosen **dataset** (see :ref:`module-datasets` for more details), but it can also be set with the ``--backbone`` CLI argument. Once loaded, the backbone model can be accessed through the **net** attribute.

Handling Begin and End of tasks and epochs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Besides the **observe** and **forward** methods, the **ContinualModel** provides the **begin_task** and **end_task** methods, which are called at the beginning and at the end of each task respectively, and the **begin_epoch** and **end_epoch** methods, which are called at the beginning and at the end of each epoch respectively. These methods can be overridden to implement custom behavior. For example, the **end_task** method can be used to save the model parameters at the end of each task.

Automatic attributes
~~~~~~~~~~~~~~~~~~~~

The base class **ContinualModel** provides a few properties that are automatically set during the incremental training (see :ref:`ContinualModel <module-models.utils.continual_model>` for more details). The most important attributes are:

.. admonition:: Task-related attributes:

    - **current_task**: the index of the current task (starting from 0). This attribute is automatically updated at the end of each task (*after* the **end_task**).

    - **n_classes_current_task**: the number of classes in the current task.

    - **n_past_classes**: the total number of classes seen so far (past).

    - **n_seen_classes**: the total number of classes seen so far (past and current).

    - **n_classes**: the total number of classes in the dataset (past, current, and remaining).

    - **n_tasks**: the total number of tasks.

    - **task_iteration**: the number of iterations performed during the current task. This attribute is automatically updated *after* each **observe** call and is reset at the beginning of each task (*before* the **begin_task**). Can be used to implement a virtual batch size (see :ref:`module-models.twf`).

    - **classes_per_task** (alias **cpt**): the *raw* amount of classes for each task. This could be either an integer (i.e., the number of classes for each task is the same) or a list of integers (i.e., the number of classes for each task is different).

.. admonition:: Transforms and dataset-related Attributes

    - **transform**: the transform applied to the input data. This attribute is automatically set during the initialization of the model and is defined by the chosen **dataset** (see :ref:`module-datasets` for more details). In most cases, this is implemented as a `kornia <https://github.com/kornia/kornia>`_ transform (translated from PIL thanks to `to_kornia_transform` in :ref:`Kornia Utils <module-utils.kornia_utils>`). However, if a transform is not supported by the **to_kornia_transform**, it is implemented as `PIL <https://pillow.readthedocs.io/en/stable/>`_.

    - **original_transform**: the original transform defined by the chosen **dataset**. This is implemented as a `PIL <https://pillow.readthedocs.io/en/stable/>`_ transform (and not translated into `kornia` as the **transform**).

    - **normalization_transform**: the transform used to normalize the input data. As for the **weak_transform**, this is implemented as a `kornia <https://github.com/kornia/kornia>`_ transform if possible, otherwise it is implemented as `PIL <https://pillow.readthedocs.io/en/stable/>`_.

.. admonition:: Other notable attributes
    
    - **device**: the device used (e.g, ``cpu`` or ``cuda:0``).

    - **net**: the backbone model (see above).

    - **opt**: the optimizer used to train the model.

    - **loss**: the loss function, defined by the chosen **dataset** (see :ref:`module-datasets` for more details).

    - **dataset**: a reference to the chosen **dataset**, to ease the access to its attributes.

    - **args**: the arguments passed to the framework.

.. note::
    The automatic conversion between `PIL <https://pillow.readthedocs.io/en/stable/>`_ and `kornia <https://github.com/kornia/kornia>`_ is handeled by the **to_kornia_transform** function in :ref:`Kornia Utils <module-utils.kornia_utils>`, which converts (*most*) PIL transforms to kornia transforms. However, not all the transforms are supported, and thus this function *may not be always available*. If you want to use a custom transform, you have to extend the **to_kornia_transform** function.

Model parameters
~~~~~~~~~~~~~~~~~

The **get_parser** method is used to define the model-specific hyper-parameters. It is defined as a static method (see :ref:`ContinualModel <module-models.utils.continual_model>`) that takes an existing `argparse.ArgumentParser <https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser>`_ object and returns an updated version of it with the model-specific hyper-parameters added. This method is called during the initialization of the model and it is used to parse the command line arguments. The **get_parser** method must have the following signature:

.. code-block:: python

    @staticmethod
    def get_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:

        # Create the parser
        parser = argparse.ArgumentParser('MyModel parameters')

        # Add the model-specific hyper-parameters
        parser.add_argument('--my_param', type=int, default=1, help='My parameter')
        ...

        return parser

.. note::

    To remain backward compatible with the previous version of the framework, the `parser` parameter is *optional*. In this case, the method must create a new `argparse.ArgumentParser <https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser>`_ object and return it.

Once the model is selected with the command line option **--model**, the hyper-parameters are loaded and can be viewed with ``--help``.

.. _model-configurations:

Model configurations
~~~~~~~~~~~~~~~~~~~~~

To simplify the selection of the model hyper-parameters, the framework includes a few predefined configurations that can be loaded with the ``--model_config`` argument. The configurations are defined in the **models/configs** folder and can define:

- **default**: the default configuration for the model, which does *NOT* depend on the dataset or buffer size. This configuration is used if the ``--model_config`` argument is set to ``default`` (or ``base``). This is the default behaviour. A similar effect of setting the ``--model_config`` argument to ``default`` can be achieved by setting the default values in the **get_parser** method, using the **set_defaults** method of the `argparse.ArgumentParser <https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser>`_ object. The default values set in the **get_parser** method are always loaded, but can be overridden by the CLI arguments.

- **best**: the best configuration for the model for a particular dataset (and buffer size, if applicable). This configuration is used if the ``--model_config`` argument is set to ``best``.

Each configuration is defined in a file named **<model_name>.yaml** and placed in the **models/configs** folder. The configuration file is a `YAML <https://yaml.org/>`_ file that defines the hyper-parameters of the model. The hyper-parameters are defined as a dictionary with the hyper-parameter name as the key and the hyper-parameter value as the value. All hyper-parameters defined under the key ``default`` are loaded with the ``default`` configuration, while only the hyper-parameters defined at under the dataset name (and buffer size, if applicable) are loaded with the ``best`` configuration. For example, the following configuration file for **my_model** defines a default `optimizer` for the model, a `learning_rate` when trained on the **seq-cifar100** dataset, and a `optim_wd` when the buffer size is **100**:

.. code-block:: yaml

    default:
        optimizer: adam # this optimizer is set to 'adam' by default (i.e., is ALWAYS loaded)
    seq-cifar100: # all the hyper-parameters defined under 'seq-cifar100' are loaded only if the dataset is 'seq-cifar100'
        learning_rate: 0.001
        100: # all the hyper-parameters defined under '100' are loaded only if the buffer size is '100'
            optim_wd: 1e-5

Other utility methods
~~~~~~~~~~~~~~~~~~~~~

* **get_optimizer**: returns the optimizer used to train the model.

* **get_debug_iters**: used if ``--debug_mode`` is set to ``1``, it returns the number of iterations to perform during each task. By default, it returns ``5``.

* **autolog_wandb**: called after each observe, it relies on the :ref:`Magic <module-utils.magic>` module to log all the variables created in the **observe** that start with *loss* or *_wandb_*. This method can also be called manually to log custom variables by providing the ``extra`` parameter. 
    .. note::
        This method is called only if ``--debug_mode`` is set to ``0`` (i.e, it is not called during the debug mode). 

Advanced usage
---------------

The **ContinualModel** class relies on a few hooks to automatically update its internal attributes. These hooks are called before the **begin_task**, **end_task**, and **observe** methods (**meta_begin_task**, **meta_end_task**, and **meta_observe** respectively). If you want to implement a custom behavior, you can override these hooks. 

.. note::
    The **meta_observe** is responsible for removing the *unlabeled* samples (i.e., those with an associated label set to ``-1``) from the batch if the model does not support the ``--label_perc_by_class`` and ``--label_perc_by_task`` parameters.