-- phpMyAdmin SQL Dump
-- version 5.2.3
-- https://www.phpmyadmin.net/
--
-- Host: localhost
-- Generation Time: Oct 20, 2026 at 02:16 PM
-- Server version: 5.7.24
-- PHP Version: 8.3.1

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `petlo`
--

-- --------------------------------------------------------

--
-- Table structure for table `dogs`
--

CREATE TABLE `dogs` (
  `dog_id` int(11) NOT NULL,
  `owner_id` int(11) NOT NULL,
  `name` varchar(255) NOT NULL,
  `date_of_birth` date NOT NULL,
  `breed` varchar(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- --------------------------------------------------------

--
-- Table structure for table `session_statistics`
--

CREATE TABLE `session_statistics` (
  `session_id` int(11) NOT NULL,
  `trainer_id` int(11) NOT NULL,
  `dog_id` int(11) NOT NULL,
  `total_distance_ran` int(11) NOT NULL,
  `total_height_jumped` int(11) NOT NULL,
  `times_jumped` int(11) NOT NULL,
  `discs_caught` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- --------------------------------------------------------

--
-- Table structure for table `session_video`
--

CREATE TABLE `session_video` (
  `view_id` int(11) NOT NULL,
  `video_id` int(11) NOT NULL,
  `session_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- --------------------------------------------------------

--
-- Table structure for table `user_login`
--

CREATE TABLE `user_login` (
  `user_id` int(11) NOT NULL,
  `email` varchar(255) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `system_role` enum('Trainer','Owner','Admin','') NOT NULL,
  `name` varchar(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- --------------------------------------------------------

--
-- Table structure for table `video`
--

CREATE TABLE `video` (
  `video_id` int(11) NOT NULL,
  `file_path` varchar(1023) NOT NULL,
  `camera_perspective` varchar(127) NOT NULL COMMENT 'should be either ''front'' or ''side'' but more perspectives can be added',
  `video_length` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `dogs`
--
ALTER TABLE `dogs`
  ADD PRIMARY KEY (`dog_id`),
  ADD KEY `fk_dog_owner` (`owner_id`);

--
-- Indexes for table `session_statistics`
--
ALTER TABLE `session_statistics`
  ADD PRIMARY KEY (`session_id`),
  ADD KEY `fk_trainer` (`trainer_id`),
  ADD KEY `fk_Dog` (`dog_id`);

--
-- Indexes for table `session_video`
--
ALTER TABLE `session_video`
  ADD PRIMARY KEY (`view_id`),
  ADD KEY `fk_video` (`video_id`),
  ADD KEY `fk_session` (`session_id`);

--
-- Indexes for table `user_login`
--
ALTER TABLE `user_login`
  ADD PRIMARY KEY (`user_id`),
  ADD UNIQUE KEY `email` (`email`);

--
-- Indexes for table `video`
--
ALTER TABLE `video`
  ADD PRIMARY KEY (`video_id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `dogs`
--
ALTER TABLE `dogs`
  MODIFY `dog_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `session_statistics`
--
ALTER TABLE `session_statistics`
  MODIFY `session_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `session_video`
--
ALTER TABLE `session_video`
  MODIFY `view_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `user_login`
--
ALTER TABLE `user_login`
  MODIFY `user_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `video`
--
ALTER TABLE `video`
  MODIFY `video_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `dogs`
--
ALTER TABLE `dogs`
  ADD CONSTRAINT `fk_dog_owner` FOREIGN KEY (`owner_id`) REFERENCES `user_login` (`user_id`);

--
-- Constraints for table `session_statistics`
--
ALTER TABLE `session_statistics`
  ADD CONSTRAINT `fk_Dog` FOREIGN KEY (`dog_id`) REFERENCES `dogs` (`dog_id`),
  ADD CONSTRAINT `fk_trainer` FOREIGN KEY (`trainer_id`) REFERENCES `user_login` (`user_id`);

--
-- Constraints for table `session_video`
--
ALTER TABLE `session_video`
  ADD CONSTRAINT `fk_session` FOREIGN KEY (`session_id`) REFERENCES `session_statistics` (`session_id`),
  ADD CONSTRAINT `fk_video` FOREIGN KEY (`video_id`) REFERENCES `video` (`video_id`);
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
