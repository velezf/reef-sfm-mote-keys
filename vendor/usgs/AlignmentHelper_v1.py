# Alignment Helper for Metashape
# This is a helper tool for Agisoft Metashape, designed to help the user to rectify the rotation and centering of non-georeferenced data. It bundles several script tools into a pop-out window which allows the user to navigate through the project and apply the desired transformations. Please consult the README documentation to understand how the helper functions.

from PySide2 import QtCore, QtWidgets
import Metashape
import math

class AlignmentDialog(QtWidgets.QDialog):

	def __init__(self, parent):

		QtWidgets.QDialog.__init__(self, parent)
		self.setWindowTitle("Alignment Helper v1.0.1")

		# Create Main Layout
		self.__mainLayout = QtWidgets.QVBoxLayout()
		self.setLayout(self.__mainLayout)
		doc_name = f"{doc}".split('/')[-1][:-2] # retrieve document name
		self.settings = QtCore.QSettings(f"Alignment Helper {doc_name}") # assign document-specific settings 
		self.mainUI()
		self.adjustSize()
		self.exec()

	# define buttons and layout
	def mainUI(self):
		#initialize widgets
		prevChunkButton = QtWidgets.QPushButton("<- Go to &previous chunk")
		topButton = QtWidgets.QPushButton("&Top view")
		sideButton = QtWidgets.QPushButton("&Side view")
		frontButton = QtWidgets.QPushButton("&Front view")
		nextChunkButton = QtWidgets.QPushButton("Go to &next chunk ->")
		applyDefaultsButton = QtWidgets.QPushButton("Apply defaults")
		saveDefaultsButton = QtWidgets.QPushButton("Overwrite defaults")
		resetDefaultsButton = QtWidgets.QPushButton("Reset defaults")
		choose_markerLabel = QtWidgets.QLabel("Reference markers for refinement:")
		self.m1_ComboBox = QtWidgets.QComboBox()
		self.m2_ComboBox = QtWidgets.QComboBox()
		spinButton = QtWidgets.QPushButton("R&otate bounding box\n90° around Z axis")
		spinButton.setFixedSize(120, 50)
		alignButton = QtWidgets.QPushButton("A&lign\ncoordinate system")
		alignButton.setFixedSize(120, 50)
		self.flipCheckBox = QtWidgets.QCheckBox("Flip &model\nacross X axis")
		refineButton = QtWidgets.QPushButton("Ref&ine adjustment\nto midline")
		refineButton.setFixedSize(120, 50)
		self.pitchCheckBox = QtWidgets.QCheckBox("&Zero pitch")
		self.invertCheckBox = QtWidgets.QCheckBox("In&vert adjustment")
		BBoxHeightLabel = QtWidgets.QLabel("Height:")
		BBoxLengthLabel = QtWidgets.QLabel("Length:")
		BBoxWidthLabel = QtWidgets.QLabel("Width:")
		self.BBoxHeightTextBox = QtWidgets.QLineEdit('5')
		self.BBoxLengthTextBox = QtWidgets.QLineEdit('0.5')
		self.BBoxWidthTextBox = QtWidgets.QLineEdit('2.5')
		self.dynamicLengthCheckBox = QtWidgets.QCheckBox("Dynamic length")
		self.dynamicLengthCheckBox.setChecked(True)
		simulateButton = QtWidgets.QPushButton("&Apply")
		yawLabel = QtWidgets.QLabel("Spin adjustment (deg)")
		self.yawval_TextBox = QtWidgets.QLineEdit("0")
		self.yawval_TextBox.setFixedSize(75,25)
		pitchLabel = QtWidgets.QLabel("Pitch adjustment (")
		self.pitchval_TextBox = QtWidgets.QLineEdit("0")
		self.pitchval_TextBox.setFixedSize(75,25)
		self.riserunRadioButton = QtWidgets.QRadioButton("&rise/run )")
		self.degreeRadioButton = QtWidgets.QRadioButton("&degrees")
		self.degreeRadioButton.setChecked(True)
		self.swapPitchCheckBox = QtWidgets.QCheckBox("Swap pitch a&xis")
		centerButton = QtWidgets.QPushButton("&Center chunk\non midpoint")
		centerButton.setFixedSize(120, 50)
		resetButton = QtWidgets.QPushButton("Reset &bounding box")
		revertButton = QtWidgets.QPushButton("Revert")
		undoButton = QtWidgets.QPushButton("Undo")
		redoButton = QtWidgets.QPushButton("Redo")

		# set tooltips 
		applyDefaultsButton.setToolTip("<html>Reset the tool's parameter configuration to the currently saved defaults.<html>")
		saveDefaultsButton.setToolTip('<html>Save the current tool parameter configuration to be used as defaults the next time the tool is opened or the "Apply defaults" button is used.<html>')
		resetDefaultsButton.setToolTip('<html>Reset the default parameters to their original "factory settings".<html>')
		spinButton.setToolTip('<html>Maniuplate the bounding box about the Z axis, such that its rotation can be applied to the chunk with "Align coordinate system".<html>')
		alignButton.setToolTip("<html>Re-orient the chunk's local coordinate system according to the bounding box.<html>")
		self.flipCheckBox.setToolTip("<html>If the chunk appears upside down when viewed from the top, try enabling this option and aligning again.<html>")
		centerButton.setToolTip("<html>Shift the chunk such that the midpoint of the line between the two reference markers is placed on (0, 0, 0) of the 3D grid.<html>")
		refineButton.setToolTip("<html>Rotate the model about the Z axis such that the midline between the reference markers is made parallel with the X axis on the XY plane of the coordinate grid.<html>")
		self.pitchCheckBox.setToolTip("<html>If enabled, the pitch of the model about the Y axis is also adjusted, making the midline parallel to the X axis on the XZ plane.<html>")
		self.invertCheckBox.setToolTip("<html>Enable this option if refining to the midline moves the model in the opposite of the desired direction.<html>")
		self.dynamicLengthCheckBox.setToolTip('<html>If enabled, bounding box length will be calculated dynamically according to the distance between the reference markers, plus a buffer on either side equal to the "Length" input.<html>')
		resetButton.setToolTip("<html>Align the bounding box with the chunk's new rotation and position using the given dimensions.<html>")
		simulateButton.setToolTip("<html>Apply specified orientation values to simulate the real orientation of the model data.<html>")
		self.yawval_TextBox.setToolTip("<html>Value in degrees to be applied to the chunk as a rotation about the Z axis. Use a negative value to reverse rotation direction.<html>")
		self.pitchval_TextBox.setToolTip("<html>Value in degrees or rise/run to be applied to the chunk as a rotation about the Y axis. Use a negative value to reverse rotation direction.<html>")
		self.swapPitchCheckBox.setToolTip("<html>If the default axis designated for the pitch adjustment does not correspond to the desired pitch axis, undo the rotation then check this box and apply the desired pitch value.<html>")
		revertButton.setToolTip("<html>Returns the chunk and bounding box to their original transforms.<html>")
		undoButton.setToolTip("<html>Return the chunk and bounding box to their transforms one step down the transform history.<html>")
		redoButton.setToolTip("<html>Return the chunk and bounding box to their tranforms one step up the transform history.<html>")

		# build layouts
		# defaults group
		defaultsGroup = QtWidgets.QGroupBox("Default settings")
		defaultsLayout = QtWidgets.QHBoxLayout()
		defaultsLayout.addWidget(applyDefaultsButton)
		defaultsLayout.addWidget(saveDefaultsButton)
		defaultsLayout.addWidget(resetDefaultsButton)
		defaultsGroup.setLayout(defaultsLayout)
		
 		# initialize nested layouts: Navigation
		prevNextLayout = QtWidgets.QHBoxLayout()
		prevNextLayout.addWidget(prevChunkButton)
		prevNextLayout.addWidget(nextChunkButton)
		
		changeViewLayout = QtWidgets.QHBoxLayout()
		changeViewLayout.addWidget(topButton)
		changeViewLayout.addWidget(sideButton)
		changeViewLayout.addWidget(frontButton)
		
		# merge navigation layouts
		navLayout = QtWidgets.QVBoxLayout()
		navLayout.addLayout(prevNextLayout)
		navLayout.addLayout(changeViewLayout)
		
		# group the navigation layouts
		navGroup = QtWidgets.QGroupBox("Navigation")
		navGroup.setLayout(navLayout)
		
		# initialize nested layouts: Primary alignment
		cs_alignLayout = QtWidgets.QHBoxLayout()
		cs_alignLayout.addWidget(spinButton)
		cs_alignLayout.addWidget(alignButton)
		cs_alignLayout.addWidget(self.flipCheckBox)
		
		# merge layouts into primary alignment group
		primaryAlignGroup = QtWidgets.QGroupBox("Primary alignment")
		primaryAlignLayout = QtWidgets.QVBoxLayout()
		primaryAlignLayout.addLayout(cs_alignLayout)
		primaryAlignGroup.setLayout(primaryAlignLayout)
		
		# initialize nested layouts: Refinement
		choose_markerLayout = QtWidgets.QHBoxLayout()
		choose_markerLayout.addWidget(choose_markerLabel)
		choose_markerLayout.addWidget(self.m1_ComboBox)
		choose_markerLayout.addWidget(self.m2_ComboBox)
		
		refineButtonLayout = QtWidgets.QHBoxLayout()
		refineButtonLayout.addWidget(centerButton)
		refineButtonLayout.addWidget(refineButton)
		refineParamsLayout = QtWidgets.QVBoxLayout()
		refineParamsLayout.addWidget(self.invertCheckBox)
		refineParamsLayout.addWidget(self.pitchCheckBox)
		refineButtonLayout.addLayout(refineParamsLayout)
		
		# initialize nested layouts: Bounding box
		BBoxGroup = QtWidgets.QGroupBox("Bounding box")
		BBoxLayout = QtWidgets.QVBoxLayout()
		BBoxSizeLabelsLayout = QtWidgets.QHBoxLayout()
		BBoxSizeLabelsLayout.addWidget(BBoxLengthLabel)
		BBoxSizeLabelsLayout.addWidget(BBoxWidthLabel)
		BBoxSizeLabelsLayout.addWidget(BBoxHeightLabel)
		BBoxSizeLayout = QtWidgets.QHBoxLayout()
		BBoxSizeLayout.addWidget(self.BBoxLengthTextBox)
		BBoxSizeLayout.addWidget(self.BBoxWidthTextBox)
		BBoxSizeLayout.addWidget(self.BBoxHeightTextBox)
		BBoxLayout.addLayout(BBoxSizeLabelsLayout)
		BBoxLayout.addLayout(BBoxSizeLayout)
		resetLayout = QtWidgets.QHBoxLayout()
		resetLayout.addWidget(self.dynamicLengthCheckBox)
		resetLayout.addWidget(resetButton)
		BBoxLayout.addLayout(resetLayout)
		BBoxGroup.setLayout(BBoxLayout)
		
		# merge layouts into refinement group
		refineGroup = QtWidgets.QGroupBox("Refinement")
		refineLayout = QtWidgets.QVBoxLayout()
		refineLayout.addLayout(choose_markerLayout)
		refineLayout.addLayout(refineButtonLayout)
		refineLayout.addWidget(BBoxGroup)
		refineGroup.setLayout(refineLayout)
		
		# simulate group
		simGroup = QtWidgets.QGroupBox("Simulate real-world orientation")
		simVals_Layout = QtWidgets.QVBoxLayout()
		simYaw_Layout = QtWidgets.QHBoxLayout()
		simYaw_Layout.addWidget(self.yawval_TextBox)
		simYaw_Layout.addWidget(yawLabel)
		simPitch_Layout = QtWidgets.QHBoxLayout()
		simPitch_Layout.addWidget(self.pitchval_TextBox)
		simPitch_Layout.addWidget(pitchLabel)
		simPitch_Layout.addWidget(self.degreeRadioButton)
		simPitch_Layout.addWidget(self.riserunRadioButton)
		simPitch_Layout.addStretch()
		executeLayout = QtWidgets.QHBoxLayout()
		executeLayout.addWidget(self.swapPitchCheckBox)
		executeLayout.addStretch()
		executeLayout.addWidget(simulateButton)
		simPitch_UpperLayout = QtWidgets.QVBoxLayout()
		simPitch_UpperLayout.addLayout(executeLayout)
		simVals_Layout.addLayout(simYaw_Layout)
		simVals_Layout.addLayout(simPitch_Layout)
		simVals_Layout.addLayout(simPitch_UpperLayout)
		simGroup.setLayout(simVals_Layout)
		
		# revert / undo layout
		revertUndoLayout = QtWidgets.QHBoxLayout()
		revertUndoLayout.addWidget(revertButton)
		revertUndoLayout.addStretch()
		revertUndoLayout.addWidget(undoButton)
		revertUndoLayout.addWidget(redoButton)

		# merge alingment subgroups into Alignment group
		alignLayout = QtWidgets.QVBoxLayout()
		alignLayout.addWidget(primaryAlignGroup)
		alignLayout.addWidget(refineGroup)
		alignLayout.addWidget(simGroup)
		alignLayout.addLayout(revertUndoLayout)
		alignGroup = QtWidgets.QGroupBox("Alignment")
		alignGroup.setLayout(alignLayout)
		
		# merge high-level groups into main layout
		internalLayout = QtWidgets.QVBoxLayout()
		internalLayout.addWidget(navGroup)
		internalLayout.addWidget(defaultsGroup)
		internalLayout.addWidget(alignGroup)
		self.__mainLayout.addLayout(internalLayout)
		
		# connect buttons to their functions
		prevChunkButton.clicked.connect(self.prevChunkButtonClicked)
		spinButton.clicked.connect(self.spinButtonClicked)
		alignButton.clicked.connect(self.alignButtonClicked)
		refineButton.clicked.connect(self.refineButtonClicked)
		simulateButton.clicked.connect(self.simulateButtonClicked)
		centerButton.clicked.connect(self.centerButtonClicked)
		topButton.clicked.connect(self.topButtonClicked)
		sideButton.clicked.connect(self.sideButtonClicked)
		frontButton.clicked.connect(self.frontButtonClicked)
		resetButton.clicked.connect(self.resetButtonClicked)
		nextChunkButton.clicked.connect(self.nextChunkButtonClicked)
		saveDefaultsButton.clicked.connect(self.saveDefaultsButtonClicked)
		applyDefaultsButton.clicked.connect(self.applyDefaultsButtonClicked)
		resetDefaultsButton.clicked.connect(self.resetDefaultsButtonClicked)
		revertButton.clicked.connect(self.revertButtonClicked)
		undoButton.clicked.connect(self.undoButtonClicked)
		redoButton.clicked.connect(self.redoButtonClicked)

		# denote which button actions will update the marker options
		markerOptsButtons = [prevChunkButton, nextChunkButton]
		for b in markerOptsButtons:
			b.clicked.connect(self.updateMarkers)

		# denote which button actions will contribute to the transform history
		transformButtons = [spinButton, alignButton, centerButton, refineButton, resetButton, simulateButton]
		for b in transformButtons:
			b.clicked.connect(self.recordTransform)

		# define dictionaries for revert and undo  
		self.transforms_hist = dict()
		self.bbox_R_hist = dict()
		self.bbox_C_hist = dict()
		self.chunk_rec_count = dict()
		self.chunk_undo_idx = dict()
		for c in doc.chunks:
			self.chunk_undo_idx[c.label] = 0
			self.chunk_undo_idx[c.label] = 0
			self.chunk_rec_count[c.label] = 0

		# populate reference marker options 
		self.updateMarkers()

		# retrieve saved setting values if possible:
		in_settings = self.settings.contains
		setval = self.settings.value
		if in_settings('flipX'):
			self.flipCheckBox.setChecked(str2bool(setval('flipX')))
		if in_settings('marker1'):
			self.m1_ComboBox.setCurrentText(setval('marker1'))
		if in_settings('marker2'):
			self.m2_ComboBox.setCurrentText(setval('marker2'))
		if in_settings('invAdj'):
			self.invertCheckBox.setChecked(str2bool(setval('invAdj')))
		if in_settings('zeroPitch'):
			self.pitchCheckBox.setChecked(str2bool(setval('zeroPitch')))
		if in_settings('length'):
			self.BBoxLengthTextBox.setText(setval('length'))
		if in_settings('width'):
			self.BBoxWidthTextBox.setText(setval('width'))
		if in_settings('height'):
			self.BBoxHeightTextBox.setText(setval('height'))
		if in_settings('dynamLength'):
			self.dynamicLengthCheckBox.setChecked(str2bool(setval('dynamLength')))
		if in_settings('spin'):
			self.yawval_TextBox.setText(setval('spin'))
		if in_settings('pitch'):
			self.pitchval_TextBox.setText(setval('pitch'))
		if in_settings('deg'):
			self.degreeRadioButton.setChecked(str2bool(setval('deg')))
		if in_settings('r_r'):
			self.riserunRadioButton.setChecked(str2bool(setval('r_r')))
		if in_settings('swapPitch'):
			self.swapPitchCheckBox.setChecked(str2bool(setval('swapPitch')))

	# define helper functions
	def getChunkAndLabel(self):
		c = doc.chunk
		label = c.label
		return c, label
	
	def retrieveMarkers(self):
		# retrieve list of markers
		markers = [m.label for m in doc.chunk.markers]
		markers.sort()
		return markers
	
	def updateMarkers(self):
		# update marker combo box options
		markers = self.retrieveMarkers()
		self.m1_ComboBox.clear()
		self.m2_ComboBox.clear() # prevents duplication in case marker selection is already populated
		self.m1_ComboBox.addItems(markers)
		self.m2_ComboBox.addItems(markers)
		self.m2_ComboBox.setCurrentText(markers[1]) # set m2 to be different from m1

	def saveDefaultsButtonClicked(self):
		defval = self.settings.setValue
		defval('flipX', self.flipCheckBox.isChecked())
		defval('marker1', self.m1_ComboBox.currentText())
		defval('marker2', self.m2_ComboBox.currentText())
		defval('invAdj', self.invertCheckBox.isChecked())
		defval('zeroPitch', self.pitchCheckBox.isChecked())
		defval('length', self.BBoxLengthTextBox.text())
		defval('width', self.BBoxWidthTextBox.text())
		defval('height', self.BBoxHeightTextBox.text())
		defval('dynamLength', self.dynamicLengthCheckBox.isChecked())
		defval('spin', self.yawval_TextBox.text())
		defval('pitch', self.pitchval_TextBox.text())
		defval('deg', self.degreeRadioButton.isChecked())
		defval('r_r', self.riserunRadioButton.isChecked())
		defval('swapPitch', self.swapPitchCheckBox.text())
		
	def resetDefaultsButtonClicked(self):
		markers = self.retrieveMarkers()
		defval = self.settings.setValue
		defval('alignToBBox', True)
		defval('alignToTrackBall', False)
		defval('flipX', False)
		defval('marker1', markers[0])
		defval('marker2', markers[1])
		defval('invAdj', False)
		defval('zeroPitch', False)
		defval('length', '0.5')
		defval('width', '2.5')
		defval('height', '5')
		defval('spin', '0')
		defval('pitch', '0')
		defval('dynamLength', True)
		defval('deg', True)
		defval('r_r', False)
		defval('swapPitch', False)
		
	def applyDefaultsButtonClicked(self):
		setval = self.settings.value
		self.flipCheckBox.setChecked(str2bool(setval('flipX')))
		self.m1_ComboBox.setCurrentText(setval('marker1'))
		self.m2_ComboBox.setCurrentText(setval('marker2'))
		self.invertCheckBox.setChecked(str2bool(setval('invAdj')))
		self.pitchCheckBox.setChecked(str2bool(setval('zeroPitch')))
		self.BBoxLengthTextBox.setText(setval('length'))
		self.BBoxWidthTextBox.setText(setval('width'))
		self.BBoxHeightTextBox.setText(setval('height'))
		self.yawval_TextBox.setText(setval('spin'))
		self.pitchval_TextBox.setText(setval('pitch'))
		self.dynamicLengthCheckBox.setChecked(str2bool(setval('dynamLength')))
		self.degreeRadioButton.setChecked(str2bool(setval('deg')))
		self.riserunRadioButton.setChecked(str2bool(setval('r_r')))
		self.swapPitchCheckBox.setChecked(str2bool(setval('swapPitch')))

	def getViewpointTransformMatrix(self):
		# obtain transformation matrix from viewpoint

		c, label = self.getChunkAndLabel()
		T = c.transform.matrix
		v_t = T.translation() 
		
		if c.crs:
			m = c.crs.localframe(v_t)
		else:
			m = Metashape.Matrix().Diag([1,1,1,1])

		R = m.rotation() 
		return R

	def transform(self):
		# transform the viewpoint

		R = self.getViewpointTransformMatrix()
		# obtain Omega/Phi/Kappa rotation matrix
		newR = Metashape.Utils.opk2mat([self.omega, self.phi, self.kappa])
		# apply transformation
		Metashape.app.model_view.viewpoint.rot = R.inv() * newR

	def prevChunkButtonClicked(self):
		# navigate backward through chunk list

		chunk = doc.chunk
		i = 0
		chunkdict = {}
		
		#build dictionary to index chunks
		for c in doc.chunks:
			chunkdict[c.label] = i
			i += 1
		
		#retrieve current chunk index
		for c in chunkdict:
			if chunk.label == c:
				n = (chunkdict[c])
		
		#activate previous chunk
		if n > 0:
			doc.chunk = doc.chunks[n-1]
		else: #loop back to last chunk if beginning of list has been reached
			doc.chunk = doc.chunks[-1] 
	
	def nextChunkButtonClicked(self):
		# navigate forward through chunk index

		chunk = doc.chunk
		i = 0
		chunkdict = {}
		
		for c in doc.chunks:
			chunkdict[c.label] = i
			i += 1
		
		for c in chunkdict:
			if chunk.label == c:
				n = (chunkdict[c])
				
		#progress to next chunk
		if n+1 < i:
			doc.chunk = doc.chunks[n+1]
		else: #loop back to first chunk if end of list has been reached
			doc.chunk = doc.chunks[0] 

	def recordTransform(self):
		# record each bbox and chunk transform in a dictionary indexed by chunk label and number of transforms

		c, label = self.getChunkAndLabel()

		# check if undo has occurred
		if self.chunk_rec_count[label] > self.chunk_undo_idx[label]:
			# proceed from current undo node; transform records ahead of the undo node will be overwritten
			self.chunk_rec_count[label] = self.chunk_undo_idx[label] 
		else: 
			# proceed from current transform node
			self.chunk_rec_count[label] += 1 

		# record transforms
		rec_label = f"{label}_{self.chunk_rec_count[label]}"
		self.transforms_hist[rec_label] = c.transform.matrix
		self.bbox_R_hist[rec_label] = c.region.rot
		self.bbox_C_hist[rec_label] = c.region.center
		# update undo index to match transform record count
		self.chunk_undo_idx[label] = self.chunk_rec_count[label]

	def revertButtonClicked(self):
		# apply original transform to chunk and bounding box

		c, label = self.getChunkAndLabel()
		c.transform.matrix = orig_transforms[label]
		c.region.rot = orig_R[label]
		c.region.center = orig_C[label]
		# record the reversion in the transform history
		self.recordTransform()

	def undoButtonClicked(self):
		# go to the previous transform from the current position along the transform-dictionary index

		c, label = self.getChunkAndLabel()
		# check if undo is possible
		if self.chunk_undo_idx[label] <= 1:
			raise Exception('Cannot undo  further; first transform reached.\nUse "Revert" to return to the chunk to its original transform.')
		self.chunk_undo_idx[label] -= 1 # each "undo" click moves the index down one node
		undo_label = f"{label}_{self.chunk_undo_idx[label]}"
		c.transform.matrix = self.transforms_hist[undo_label]
		c.region.rot = self.bbox_R_hist[undo_label]
		c.region.center = self.bbox_C_hist[undo_label]

	def redoButtonClicked(self):
		# go to the next transform from the current position along the transform-dictionary index

		c, label = self.getChunkAndLabel()
		# check if redo is possible
		if self.chunk_undo_idx[label] == self.chunk_rec_count[label]:
			raise Exception("Cannot redo further; reached most recent transform.")
		else: 
			self.chunk_undo_idx[label] += 1 # each "redo" click moves the index up one node
		undo_label = f"{label}_{self.chunk_undo_idx[label]}"
		c.transform.matrix = self.transforms_hist[undo_label]
		c.region.rot = self.bbox_R_hist[undo_label]
		c.region.center = self.bbox_C_hist[undo_label]

	def topButtonClicked(self):
		# establish top-down view

		self.omega = 0.0 
		self.phi = 0.0 
		self.kappa = 0.0
		self.transform()

	def sideButtonClicked(self):
		# establish side view

		self.omega = 0.0
		self.phi = -90.0
		self.kappa = -90.0
		self.transform()
		
	def frontButtonClicked(self):
		# establish front view

		self.omega = 90 
		self.phi = 0.0
		self.kappa = 0.0
		self.transform()
		
	def spinButtonClicked(self):
		# spin the bounding box 90 degrees counterclockwise

		chunk = doc.chunk
		Z3_90 = Metashape.Matrix([[0, -1, 0],
								  [1, 0, 0],
								  [0, 0, 1]])
		chunk.region.rot *= Z3_90
		
	def alignButtonClicked(self):
		# align the chunk's coordinate system to the bounding box

		chunk = doc.chunk
		R = chunk.region.rot     # Bounding box rotation matrix
		C = chunk.region.center  # Bounding box center vector

		if chunk.transform.matrix: # retrieve scale factor S from chunk transform matrix
			T = chunk.transform.matrix
			s = math.sqrt(T[0, 0] ** 2 + T[0, 1] ** 2 + T[0, 2] ** 2)  # scaling # T.scale()
			if self.flipCheckBox.isChecked():
				S = Metashape.Matrix().Diag([s, s*(-1), s, 1])                  # scale matrix
			else: S = Metashape.Matrix().Diag([s, s, s, 1])
		else:
			if self.flipCheckBox.isChecked():
				S = Metashape.Matrix().Diag([1, -1, 1, 1])
			else:
				S = Metashape.Matrix().Diag([1, 1, 1, 1])

		# build new transform matrix from bounding box rotation and center values
		T = Metashape.Matrix([[R[0, 0], R[0, 1], R[0, 2], C[0]],
							  [R[1, 0], R[1, 1], R[1, 2], C[1]],
							  [R[2, 0], R[2, 1], R[2, 2], C[2]],
							  [      0,       0,       0,    1]])
		# bring chunk into line with bounding box
		chunk.transform.matrix = S * T.inv() 

	def getRefMarkerPositions(self):
		# retrieve local-coordinate positions of reference markers

		m1 = get_marker(f"{self.m1_ComboBox.currentText()}", doc.chunk).position
		m2 = get_marker(f"{self.m2_ComboBox.currentText()}", doc.chunk).position
		return m1, m2

	def centerButtonClicked(self):
		# center the chunk on the midpoint of the midline

		c, label = self.getChunkAndLabel()
		M = c.transform.matrix

		#get marker positions and midpoint
		m1, m2 = self.getRefMarkerPositions()
		mid = (m1+m2)/2

		#transform midpoint to homogenous coordinates
		A = M.mulv(mid)*(-1)

		#build new transformation matrix centered on midpoint
		M_new = Metashape.Matrix([[M[0, 0], M[0, 1], M[0, 2], A[0]],
							  [M[1, 0], M[1, 1], M[1, 2], A[1]],
							  [M[2, 0], M[2, 1], M[2, 2], A[2]],
							  [      0,       0,       0,    1]])

		#apply M_new
		c.transform.matrix = M_new
		print(f"New center (homogenous coordinates) for {label}: {A}")
		
	def refineButtonClicked(self):
		# ensure the midline is parallel to the X axis
		chunk = doc.chunk
		M = chunk.transform.matrix
		m1, m2 = self.getRefMarkerPositions()
		
		#retreive yaw and pitch of the midline
		diff = M.mulp(m1)-M.mulp(m2)
		yaw = math.degrees(math.atan(diff[1]/diff[0]))
		pitch = math.degrees(math.atan(diff[2]/diff[0]))
	
		#convert euler angles of midline to matrix and apply new rotation schema to chunk rotation matrix
		if self.pitchCheckBox.isChecked():
			E = Metashape.Utils.euler2mat([yaw, pitch, 0])
		else:
			E = Metashape.Utils.euler2mat([yaw, 0, 0])
			
		if self.invertCheckBox.isChecked():
			chunk.transform.rotation *= E.inv()
		else:
			chunk.transform.rotation *= E
	
	def resetButtonClicked(self):
		# resize the bounding box to accomodate the new chunk orientation
		BBox_X = float(self.BBoxLengthTextBox.text())
		BBox_Y = float(self.BBoxWidthTextBox.text())
		BBox_Z = float(self.BBoxHeightTextBox.text())
		
		c = doc.chunk
		M = c.transform.matrix
		new_center = Metashape.Vector([0, 0, 0])
		new_center_int = M.inv().mulp(new_center)
		c.region.center = new_center_int
		new_rot = Metashape.Matrix([[1,0,0], [0,-1,0], [0,0,1]])
		c.region.rot = (M.rotation().inv() * new_rot)
		
		if self.dynamicLengthCheckBox.isChecked():
			m1, m2 = self.getRefMarkerPositions()
			# Retrieve positional differential between marker1 and marker2
			diff = M.mulp(m1)-M.mulp(m2) 
			# Create list of absolute differentials
			diffs = [abs(d) for d in diff]

			# Sort diffs smallest-to-largest and extract the two largest
			diffs = sorted(diffs)
			diff1 = diffs[-1]
			diff2 = diffs[-2]
			# Calculate transect distance with Pythagorean theorem
			transect_dist = math.sqrt(diff1**2 + diff2**2)
			# Calculate bbox size with transect distance plus double the BBox_X input 
			# (BBox_X doubled to apply buffer on either side of the transect length) 
			new_size_bbox = Metashape.Vector([transect_dist+BBox_X*2, BBox_Y, BBox_Z]) # resize bounding box with dynamic length
		
			transect_dist = round(transect_dist,2)
			print(f"Transect distance: {transect_dist}")
		else:
			new_size_bbox = Metashape.Vector([BBox_X, BBox_Y, BBox_Z]) # resize bounding box with static length input
			
		bbox_loc = new_size_bbox / c.transform.scale
		c.region.size = bbox_loc
		
	def simulateButtonClicked(self):
		# apply simulated orienation values to the chunk
		chunk = doc.chunk
		# retrieve simulated spin value
		yaw_deg = float(self.yawval_TextBox.text())
		
		# check specified pitch unit (rise/run or degrees)
		if self.riserunRadioButton.isChecked():
			pitch_grd = eval(self.pitchval_TextBox.text()) # retrieve rise/run grade
			pitch_deg = math.degrees(math.atan(pitch_grd))
		else: 
			pitch_deg = float(self.pitchval_TextBox.text())
		
		if self.swapPitchCheckBox.isChecked(): # apply pitch along designated axis
			E = Metashape.Utils.euler2mat([yaw_deg, 0, pitch_deg])
		else:
			E = Metashape.Utils.euler2mat([yaw_deg, pitch_deg, 0])
		
		chunk.region.rot *= E # apply rotation to bounding box
		
		# ensure chunk and bounding box remain aligned
		self.alignButtonClicked() 
		chunk.region.rot *= E.inv()

def main():
	
	# define global functions
	global get_marker
	def get_marker(label, chunk):
		# retrieve Metashape marker from its label

		for marker in chunk.markers:
			if label == marker.label:
				return marker
		raise Exception(f"Marker not found: {label}")
		
	global str2bool
	def str2bool(string):
		# convert 'true' string to True boolean (used for parsing settings)

		if string == 'true':
			return True
		else:
			return False

	def getOrigTransforms():
		# build dictionaries of initial transform matrices, bounding box matrices, and bounding box center coordinates on startup (referenced in the "revertButtonClicked" function).
		
		orig_transforms = dict()
		orig_R = dict()
		orig_C = dict()
		for c in doc.chunks:
			if c.transform.matrix:
				orig_transforms[c.label] = c.transform.matrix
			orig_R[c.label] = c.region.rot
			orig_C[c.label] = c.region.center
		return orig_transforms, orig_R, orig_C
	
	# define global variables
	global doc
	doc = Metashape.app.document
	# build dictionaries for initial transforms 
	global orig_transforms, orig_R, orig_C
	orig_transforms, orig_R, orig_C = getOrigTransforms()

	# instantiate the app
	app = QtWidgets.QApplication.instance()
	parent = app.activeWindow()
	dlg = AlignmentDialog(parent)

#add Alignment Helper to "Helpers" tab in Metashape ribbon
Metashape.app.addMenuItem("Helpers/Alignment Helper v1.0.1", main)
print("'Alignment Helper v1.0.1' added to 'Helpers'")
