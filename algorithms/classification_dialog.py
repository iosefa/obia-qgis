"""Classification dialogs with holdout controls that follow the test input."""

from qgis.core import Qgis, QgsProcessingFeatureSourceDefinition, QgsProperty

if Qgis.QGIS_VERSION_INT >= 40000:
    from processing.gui.algorithm_widget import AlgorithmWidget as AlgorithmDialog
else:
    from processing.gui.AlgorithmDialog import AlgorithmDialog


class ClassificationDialog(AlgorithmDialog):
    def __init__(self, algorithm, parent=None):
        super().__init__(algorithm, parent=parent)
        self._test_wrapper = self.mainWidget().wrappers["TEST"]
        self._fraction_wrapper = self.mainWidget().wrappers["TEST_FRACTION"]
        self._test_wrapper.widgetValueHasChanged.connect(self._update_holdout_visibility)
        self._update_holdout_visibility()

    def _update_holdout_visibility(self, *_):
        test = self._test_wrapper.parameterValue()
        if isinstance(test, QgsProcessingFeatureSourceDefinition):
            test = test.source
        if isinstance(test, QgsProperty):
            test, _ = test.valueAsString(
                self.mainWidget().processing_context.expressionContext()
            )

        # Keep the value intact so clearing the test input restores the holdout.
        visible = not bool(test)
        for widget in (
            self._fraction_wrapper.wrappedLabel(),
            self._fraction_wrapper.wrappedWidget(),
        ):
            if widget is not None:
                widget.setVisible(visible)
